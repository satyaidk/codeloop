"""The tools the agent can call, and what each call shows the developer.

Which tools a run gets depends on the chat: memory tools only when memory is on, file tools only when a
project is open, edit and command tools only when the developer allowed them for that chat. A tool the
model wasn't given can't be called, so permissions don't depend on the model obeying the prompt.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field

from app.llm.base import ToolCall, ToolSpec
from app.memory import MemoryStore, display_text
from app.workspace import Workspace, WorkspaceError

logger = logging.getLogger(__name__)

MAX_NOTE_CHARS = 600
MAX_RESULT_CHARS = 16_000  # what one tool result may add to the model's context


@dataclass
class ToolResult:
    ok: bool
    content: str  # what the model sees
    summary: str  # one line for the developer
    detail: str | None = None  # expandable text: a diff, command output, recalled notes
    kind: str = "text"  # "diff" | "output" | "notes" | "text"
    file_read: str | None = None
    file_changed: str | None = None
    command: str | None = None
    exit_code: int | None = None
    note_saved: bool = False


@dataclass
class Toolbox:
    workspace: Workspace | None
    memory: MemoryStore | None
    scope: str
    allow_edits: bool = False
    allow_commands: bool = False
    allow_notes: bool = True  # off for evaluation runs, which must not change the memory they measure
    _seen: dict[str, int] = field(default_factory=dict)

    def specs(self) -> list[ToolSpec]:
        tools: list[ToolSpec] = []
        if self.memory is not None:
            tools.append(RECALL)
            if self.allow_notes:
                tools.append(SAVE_NOTE)
        if self.workspace is not None:
            tools += [LIST_FILES, READ_FILE, SEARCH_CODE, GIT_CHANGES]
            if self.allow_edits:
                tools += [EDIT_FILE, WRITE_FILE]
            if self.allow_commands:
                tools.append(_run_command_spec(self.workspace.allowlist))
        return tools

    def label(self, call: ToolCall) -> str:
        """What the agent is doing, in the developer's words, shown while the tool runs."""
        a = call.arguments
        path = a.get("path") or "."
        return {
            "recall_memory": f"Recalling “{a.get('query', '')}”",
            "save_note": "Saving a note to project memory",
            "list_files": f"Listing {path}",
            "read_file": f"Reading {path}",
            "search_code": f"Searching for “{a.get('pattern', '')}”",
            "git_changes": "Checking uncommitted changes",
            "edit_file": f"Editing {path}",
            "write_file": f"Writing {path}",
            "run_command": f"Running {a.get('command', '')}",
        }.get(call.name, f"Using {call.name}")

    async def run(self, call: ToolCall) -> ToolResult:
        allowed = {t.name for t in self.specs()}
        if call.name not in allowed:
            return _error(f"There is no tool called '{call.name}' in this chat.")
        key = f"{call.name}:{json.dumps(call.arguments, sort_keys=True)}"
        self._seen[key] = self._seen.get(key, 0) + 1
        if self._seen[key] > 2 and call.name not in ("run_command", "git_changes"):
            return _error("You already made this exact call twice. Use the earlier result, or try something else.")
        try:
            result = await getattr(self, f"_{call.name}")(**_known_args(call))
        except WorkspaceError as exc:
            return _error(str(exc))
        except TypeError as exc:
            return _error(f"Wrong arguments for {call.name}: {exc}")
        except Exception as exc:  # a tool failure goes back to the model; it never ends the run
            logger.exception("tool %s failed", call.name)
            return _error(f"{call.name} failed: {exc}")
        if len(result.content) > MAX_RESULT_CHARS:
            result.content = result.content[:MAX_RESULT_CHARS] + "\n... (cut to keep the context small)"
        return result

    # ---- memory ----

    async def _recall_memory(self, query: str) -> ToolResult:
        notes = await self.memory.recall(self.scope, query)
        if not notes:
            return ToolResult(True, "No notes match. Look in the code instead.", f"No notes about “{query}”")
        lines = [f"- {n.text}" + (f" ({n.occurred_at[:10]})" if n.occurred_at else "") for n in notes]
        shown = "\n".join(f"• {display_text(n.text)}" for n in notes)
        return ToolResult(True, "\n".join(lines), f"Recalled {len(notes)} notes about “{query}”", shown, "notes")

    async def _save_note(self, note: str) -> ToolResult:
        note = note.strip()
        if not note:
            return _error("The note is empty.")
        await self.memory.remember(self.scope, note[:MAX_NOTE_CHARS], context="agent note")
        return ToolResult(
            True, "Saved.", "Saved a note to project memory", note[:MAX_NOTE_CHARS], "notes", note_saved=True
        )

    # ---- reading ----

    async def _list_files(self, path: str = ".", depth: int = 2) -> ToolResult:
        text, count = await asyncio.to_thread(self.workspace.list_tree, path, int(depth or 2))
        return ToolResult(True, text, f"Listed {path} · {count} entries")

    async def _read_file(self, path: str, start_line: int | None = None, end_line: int | None = None) -> ToolResult:
        text, rel, summary = await asyncio.to_thread(self.workspace.read, path, _int(start_line), _int(end_line))
        return ToolResult(True, text, summary, file_read=rel)

    async def _search_code(self, pattern: str, path: str = ".", glob: str | None = None) -> ToolResult:
        text, total = await asyncio.to_thread(self.workspace.search, pattern, path, glob or None)
        noun = "match" if total == 1 else "matches"
        return ToolResult(True, text, f"{total} {noun} for “{pattern}”", text if total else None, "output")

    async def _git_changes(self) -> ToolResult:
        text = await asyncio.to_thread(self.workspace.git_changes)
        return ToolResult(True, text, "Checked uncommitted changes", text, "diff")

    # ---- writing ----

    async def _edit_file(self, path: str, old_text: str, new_text: str) -> ToolResult:
        change = await asyncio.to_thread(self.workspace.edit, path, old_text, new_text)
        return _change_result("Edited", change)

    async def _write_file(self, path: str, content: str) -> ToolResult:
        change = await asyncio.to_thread(self.workspace.write, path, content)
        return _change_result("Created" if change.created else "Rewrote", change)

    async def _run_command(self, command: str) -> ToolResult:
        result = await asyncio.to_thread(self.workspace.run, command)
        if result.exit_code is None:
            status = "timed out"
        else:
            status = f"exited {result.exit_code}"
        content = f"$ {result.command}\nexit code: {result.exit_code}\n\n{result.output or '(no output)'}"
        summary = f"{result.command} · {status} in {result.seconds:.1f}s"
        return ToolResult(
            True, content, summary, result.output or "(no output)", "output",
            command=result.command, exit_code=result.exit_code,
        )  # fmt: skip


def _change_result(verb: str, change) -> ToolResult:
    summary = f"{verb} {change.path} · +{change.added} −{change.removed}"
    content = f"{verb} {change.path} (+{change.added} -{change.removed} lines)."
    return ToolResult(True, content, summary, change.diff or "(no changes)", "diff", file_changed=change.path)


def _error(message: str) -> ToolResult:
    return ToolResult(False, f"Error: {message}", message)


def _int(value) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


_PARAMS: dict[str, set[str]] = {}


def _known_args(call: ToolCall) -> dict:
    """Drop arguments the tool doesn't take; small models sometimes invent extra ones."""
    return {k: v for k, v in call.arguments.items() if k in _PARAMS.get(call.name, set())}


def _spec(name: str, description: str, properties: dict, required: list[str]) -> ToolSpec:
    _PARAMS[name] = set(properties)
    schema = {"type": "object", "properties": properties, "required": required, "additionalProperties": False}
    return ToolSpec(name, description, schema)


_PATH = {"type": "string", "description": "Path relative to the project root, e.g. src/app.py"}

RECALL = _spec(
    "recall_memory",
    "Search your long-term notes about this project: architecture, where things live, how to build and test "
    "it, past bugs and fixes, and the developer's preferences. Much cheaper than reading code, so try it first "
    "when you need to know where something is or how it works.",
    {"query": {"type": "string", "description": "What you want to know, in plain words"}},
    ["query"],
)
SAVE_NOTE = _spec(
    "save_note",
    "Save one durable fact about this project to long-term memory so you won't have to rediscover it next "
    "time, e.g. 'Tests run with `pytest -q` from the repo root' or 'src/db.ts owns all SQL queries'. Save "
    "facts, not plans; one or two sentences with exact paths and names.",
    {"note": {"type": "string", "description": "The fact to remember"}},
    ["note"],
)
LIST_FILES = _spec(
    "list_files",
    "List the files and folders in the project (dependency and build folders are skipped).",
    {
        "path": {**_PATH, "description": "Folder to list, relative to the project root. Default: the root"},
        "depth": {"type": "integer", "description": "How many folder levels to show, 1-4. Default 2"},
    },
    [],
)
READ_FILE = _spec(
    "read_file",
    "Read a text file with line numbers, up to 400 lines per call. For long files, read the part you need "
    "with start_line and end_line.",
    {
        "path": _PATH,
        "start_line": {"type": "integer", "description": "First line to read (1-based)"},
        "end_line": {"type": "integer", "description": "Last line to read"},
    },
    ["path"],
)
SEARCH_CODE = _spec(
    "search_code",
    "Search file contents with a regular expression (case-insensitive). Returns matching lines as "
    "path:line: text. Use it to find definitions, usages and error messages.",
    {
        "pattern": {"type": "string", "description": "Regular expression or plain text to find"},
        "path": {**_PATH, "description": "Folder or file to search in. Default: the whole project"},
        "glob": {"type": "string", "description": "Only search files matching this pattern, e.g. *.py"},
    },
    ["pattern"],
)
GIT_CHANGES = _spec(
    "git_changes",
    "Show the uncommitted changes in the project: git status plus the staged and unstaged diff. Use it to "
    "review what the developer is working on.",
    {},
    [],
)
EDIT_FILE = _spec(
    "edit_file",
    "Replace one exact piece of text in a file. old_text must match the file exactly (copy it from read_file "
    "without the line numbers, keeping indentation) and must appear only once; include a few surrounding lines "
    "to make it unique.",
    {
        "path": _PATH,
        "old_text": {"type": "string", "description": "The exact text to replace"},
        "new_text": {"type": "string", "description": "The text to put in its place"},
    },
    ["path", "old_text", "new_text"],
)
WRITE_FILE = _spec(
    "write_file",
    "Create a new file, or replace a whole file. Prefer edit_file for changes to existing files.",
    {"path": _PATH, "content": {"type": "string", "description": "The complete file contents"}},
    ["path", "content"],
)


def _run_command_spec(allowlist: frozenset[str]) -> ToolSpec:
    programs = ", ".join(sorted(allowlist))
    return _spec(
        "run_command",
        "Run one command in the project root, such as the test suite, a linter or a build, and get its exit code "
        f"and output. Allowed programs: {programs}. No shell features: no pipes, &&, ; or redirects.",
        {"command": {"type": "string", "description": "The command, e.g. pytest -q tests/test_api.py"}},
        ["command"],
    )
