"""Projects on disk, and everything the agent may do inside one.

Safety rules, enforced here rather than trusted to the model:
- Every path is resolved and must stay inside the project folder (symlinks included).
- Secret files (.env, private keys, ...) are never read or written: their contents would be sent to the
  model provider.
- Commands run without a shell, one program at a time, only if the program is on the allowlist, with a
  timeout, and without this server's own API keys in their environment.
"""

from __future__ import annotations

import difflib
import fnmatch
import os
import re
import shlex
import shutil
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

# Folders that hold dependencies, build output or caches: never listed, searched or snapshotted.
IGNORED_DIRS = frozenset(
    {
        ".git", "node_modules", ".venv", "venv", "env", "__pycache__", "dist", "build", ".next", ".nuxt",
        ".svelte-kit", "target", ".idea", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", "coverage",
        ".gradle", ".turbo", ".cache", "obj", "vendor", ".parcel-cache", "htmlcov", ".eggs",
    }
)  # fmt: skip
SECRET_GLOBS = ("*.pem", "*.key", "*.p12", "*.pfx", "*.keystore", "*.jks", "id_rsa*", "id_ed25519*", "id_ecdsa*",
                ".npmrc", ".pypirc", ".netrc", "credentials.json", "secrets.*")  # fmt: skip
SAFE_ENV_SUFFIXES = (".example", ".sample", ".template", ".dist")
GIT_READ_ONLY = frozenset({"status", "diff", "log", "show", "blame", "rev-parse", "ls-files", "grep", "shortlog"})
SHELL_TOKENS = frozenset({"&&", "||", ";", "|", ">", ">>", "<", "&", "2>", "2>&1"})
# Environment variables a command must never see: the keys this server uses to call models and memory.
_PRIVATE_ENV = re.compile(
    r"^(CODELOOP_.*|HINDSIGHT_.*|(OPENAI|ANTHROPIC|GEMINI|GROQ|OPENROUTER|DEEPSEEK|MISTRAL)_API_KEY)$"
)
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

MAX_FILE_BYTES = 2_000_000
MAX_READ_LINES = 400
MAX_READ_CHARS = 40_000
MAX_WRITE_CHARS = 400_000
MAX_OUTPUT_CHARS = 12_000
MAX_DIFF_LINES = 400


class WorkspaceError(Exception):
    """A request the workspace refuses. The message is written for the model (and shown to the developer)."""


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    path: Path
    is_git: bool


@dataclass
class FileChange:
    path: str
    created: bool
    added: int
    removed: int
    diff: str


@dataclass
class CommandResult:
    command: str
    exit_code: int | None  # None when it timed out
    output: str
    seconds: float


def is_secret(rel_path: str) -> bool:
    name = PurePosixPath(rel_path).name.lower()
    if name == ".env" or (name.startswith(".env.") and not name.endswith(SAFE_ENV_SUFFIXES)):
        return True
    return any(fnmatch.fnmatch(name, pattern) for pattern in SECRET_GLOBS)


def is_binary(data: bytes) -> bool:
    return b"\0" in data[:8192]


def truncate_middle(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    """Keep the start and (mostly) the end of long output: errors and summaries usually come last."""
    if len(text) <= limit:
        return text
    head = limit // 4
    tail = limit - head
    return f"{text[:head]}\n\n... ({len(text) - limit:,} characters cut) ...\n\n{text[-tail:]}"


class Workspace:
    """One project's folder, with the operations the agent's tools are allowed to perform."""

    def __init__(self, root: Path, allowlist: frozenset[str] = frozenset(), timeout: int = 180):
        self.root = root.resolve()
        self.allowlist = allowlist
        self.timeout = timeout

    # ---- paths ----

    def resolve(self, rel: str | None) -> Path:
        rel = (rel or ".").strip().strip("\"'") or "."
        outside = WorkspaceError(f"'{rel}' is outside the project. Use a path relative to the project root.")
        candidate = Path(rel)
        if candidate.is_absolute() and _inside(candidate.resolve(), self.root):
            return candidate.resolve()
        path = rel.replace("\\", "/")
        if candidate.is_absolute() or path.startswith("/"):
            # Models often write "/src/app.py" meaning "src/app.py at the project root". Accept that only when the
            # first folder exists in the project, so "/etc/passwd" or "/tmp/x" is refused on every OS rather than
            # quietly read as a project path. A bare "/" means the project root.
            parts = [p for p in path.split("/") if p]
            if candidate.drive or (parts and not (self.root / parts[0]).exists()):
                raise outside
            path = "/".join(parts) or "."
        target = (self.root / path).resolve()
        if not _inside(target, self.root):
            raise outside
        return target

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix() or "."

    def walk_files(self, start: Path | None = None) -> Iterator[Path]:
        """Every file under `start`, skipping ignored folders, in a stable order."""
        start = start or self.root
        for dirpath, dirnames, filenames in os.walk(start):
            dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRS)
            for name in sorted(filenames):
                yield Path(dirpath) / name

    # ---- reading ----

    def list_tree(self, rel: str = ".", depth: int = 2, limit: int = 400) -> tuple[str, int]:
        start = self.resolve(rel)
        if not start.is_dir():
            raise WorkspaceError(f"'{rel}' is not a folder.")
        depth = max(1, min(depth, 4))
        lines: list[str] = []
        hidden = 0

        def visit(folder: Path, level: int) -> None:
            nonlocal hidden
            try:
                entries = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            except OSError:
                return
            for entry in entries:
                if entry.is_dir() and entry.name in IGNORED_DIRS:
                    continue
                if len(lines) >= limit:
                    hidden += 1
                    continue
                indent = "  " * level
                if entry.is_dir():
                    if level + 1 < depth:
                        lines.append(f"{indent}{entry.name}/")
                        visit(entry, level + 1)
                    else:
                        count = sum(1 for _ in _safe_iterdir(entry))
                        lines.append(f"{indent}{entry.name}/ ({count} entries)")
                else:
                    lines.append(f"{indent}{entry.name}")

        visit(start, 0)
        if hidden:
            lines.append(f"... {hidden} more entries not shown; list a subfolder to see them")
        header = f"{self.rel(start)}/" if rel not in (".", "", "/") else f"{self.root.name}/ (project root)"
        return "\n".join([header, *lines]), len(lines)

    def read_text(self, rel: str) -> tuple[Path, str]:
        path = self.resolve(rel)
        rel_path = self.rel(path)
        if is_secret(rel_path):
            raise WorkspaceError(f"'{rel_path}' may contain secrets, so it can't be read. Ask the developer instead.")
        if not path.is_file():
            hint = (
                " It's a folder; use list_files."
                if path.is_dir()
                else " Check the path with list_files or search_code."
            )
            raise WorkspaceError(f"'{rel_path}' doesn't exist.{hint}")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise WorkspaceError(f"'{rel_path}' is larger than 2 MB; search it with search_code instead.")
        data = path.read_bytes()
        if is_binary(data):
            raise WorkspaceError(f"'{rel_path}' is a binary file.")
        return path, data.decode("utf-8", errors="replace")

    def read(self, rel: str, start_line: int | None = None, end_line: int | None = None) -> tuple[str, str, str]:
        """Returns (text with line numbers for the model, relative path, a short summary)."""
        path, text = self.read_text(rel)
        rel_path = self.rel(path)
        lines = text.splitlines()
        total = len(lines)
        if total == 0:
            return f"{rel_path} is empty.", rel_path, f"Read {rel_path} (empty)"
        first = max(1, start_line or 1)
        if first > total:
            raise WorkspaceError(f"{rel_path} has only {total} lines.")
        last = min(total, end_line or first + MAX_READ_LINES - 1, first + MAX_READ_LINES - 1)
        last = max(first, last)
        width = len(str(last))
        body = "\n".join(f"{n:>{width}} | {lines[n - 1]}" for n in range(first, last + 1))
        if len(body) > MAX_READ_CHARS:
            body = body[:MAX_READ_CHARS] + "\n... (cut: the lines are very long)"
        header = f"{rel_path} (lines {first}-{last} of {total})"
        footer = (
            f"\n... {total - last} more lines. Call read_file with start_line={last + 1} to continue."
            if last < total
            else ""
        )
        return f"{header}\n{body}{footer}", rel_path, f"Read {rel_path}, lines {first}–{last} of {total}"

    def search(self, pattern: str, rel: str = ".", glob: str | None = None, max_results: int = 60) -> tuple[str, int]:
        if not pattern:
            raise WorkspaceError("Give a pattern to search for.")
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            regex = re.compile(re.escape(pattern), re.IGNORECASE)
        start = self.resolve(rel)
        files = [start] if start.is_file() else self.walk_files(start)
        results: list[str] = []
        total = 0
        for scanned, path in enumerate(files):
            if scanned > 10_000 or total > 1000:
                break
            rel_path = self.rel(path)
            if glob and not (fnmatch.fnmatch(rel_path, glob) or fnmatch.fnmatch(path.name, glob)):
                continue
            if is_secret(rel_path):
                continue
            try:
                if path.stat().st_size > 1_000_000:
                    continue
                data = path.read_bytes()
            except OSError:
                continue
            if is_binary(data):
                continue
            for number, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), start=1):
                if regex.search(line):
                    total += 1
                    if len(results) < max_results:
                        results.append(f"{rel_path}:{number}: {line.strip()[:200]}")
        if not results:
            hint = "Try a shorter, broader pattern (one identifier, no regex), or check the layout first."
            return f"No matches for /{pattern}/. {hint}", 0
        more = (
            f"\n... {total - len(results)} more matches; narrow the search with path or glob."
            if total > len(results)
            else ""
        )
        return "\n".join(results) + more, total

    # ---- writing ----

    def _writable(self, rel: str) -> tuple[Path, str]:
        path = self.resolve(rel)
        rel_path = self.rel(path)
        parts = PurePosixPath(rel_path).parts
        if rel_path == "." or path.is_dir():
            raise WorkspaceError(f"'{rel_path}' is a folder, not a file.")
        if ".git" in parts or (parts and parts[0] in IGNORED_DIRS):
            raise WorkspaceError(f"'{rel_path}' is inside a generated or version-control folder; it can't be edited.")
        if is_secret(rel_path):
            raise WorkspaceError(
                f"'{rel_path}' may hold secrets, so it can't be edited. Ask the developer to change it."
            )
        return path, rel_path

    def write(self, rel: str, content: str) -> FileChange:
        path, rel_path = self._writable(rel)
        if len(content) > MAX_WRITE_CHARS:
            raise WorkspaceError("That file is too large to write in one call.")
        old, crlf, existed = "", False, path.exists()
        if existed:
            _, raw = self.read_text(rel_path)
            old, crlf = raw.replace("\r\n", "\n"), "\r\n" in raw
        new = content.replace("\r\n", "\n")
        path.parent.mkdir(parents=True, exist_ok=True)
        _write(path, new, crlf)
        return _change(rel_path, old, new, created=not existed)

    def edit(self, rel: str, old_text: str, new_text: str) -> FileChange:
        path, rel_path = self._writable(rel)
        if not old_text:
            raise WorkspaceError("old_text is empty. Copy the exact text to replace from read_file.")
        _, raw = self.read_text(rel_path)
        crlf = "\r\n" in raw
        text = raw.replace("\r\n", "\n")
        old_text = old_text.replace("\r\n", "\n")
        count = text.count(old_text)
        if count == 0:
            raise WorkspaceError(
                f"old_text was not found in {rel_path}. Read the file again and copy the text exactly, "
                "without line numbers, including indentation."
            )
        if count > 1:
            raise WorkspaceError(f"old_text appears {count} times in {rel_path}. Include more surrounding lines.")
        new = text.replace(old_text, new_text.replace("\r\n", "\n"), 1)
        _write(path, new, crlf)
        return _change(rel_path, text, new, created=False)

    # ---- commands ----

    def parse_command(self, command: str) -> list[str]:
        command = command.strip()
        if not command:
            raise WorkspaceError("The command is empty.")
        if os.name == "nt":
            command = command.replace("\\", "/")  # shlex would read Windows backslashes as escapes
        try:
            args = shlex.split(command)
        except ValueError as exc:
            raise WorkspaceError(f"Couldn't parse the command: {exc}") from exc
        if any(a in SHELL_TOKENS for a in args) or "`" in command or "$(" in command:
            raise WorkspaceError("Run one command at a time, without pipes, &&, ; or redirects.")
        program = re.sub(r"\.(exe|cmd|bat|ps1|sh)$", "", PurePosixPath(args[0]).name.lower())
        if program not in self.allowlist:
            allowed = ", ".join(sorted(self.allowlist))
            raise WorkspaceError(f"'{program}' isn't on the list of programs CodeLoop may run: {allowed}.")
        if program == "git" and (len(args) < 2 or args[1] not in GIT_READ_ONLY):
            raise WorkspaceError(f"Only read-only git commands are allowed: {', '.join(sorted(GIT_READ_ONLY))}.")
        return args

    def run(self, command: str) -> CommandResult:
        args = self.parse_command(command)
        if "/" in args[0]:  # a script inside the project, like ./gradlew
            exe = self.resolve(args[0])
            if not exe.is_file():
                raise WorkspaceError(f"'{args[0]}' doesn't exist in the project.")
            executable = str(exe)
        else:
            found = shutil.which(args[0])
            if not found:
                raise WorkspaceError(f"'{args[0]}' isn't installed or isn't on the PATH of the CodeLoop server.")
            executable = found
        env = {k: v for k, v in os.environ.items() if not _PRIVATE_ENV.match(k)}
        env.update(
            {"CI": "1", "NO_COLOR": "1", "FORCE_COLOR": "0", "PYTHONUNBUFFERED": "1", "GIT_TERMINAL_PROMPT": "0"}
        )
        started = time.monotonic()
        try:
            completed = subprocess.run(
                [executable, *args[1:]],
                cwd=self.root,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=self.timeout,
                check=False,
            )
            exit_code: int | None = completed.returncode
            raw = completed.stdout or b""
        except subprocess.TimeoutExpired as exc:
            exit_code = None
            raw = (exc.output or b"") + f"\n[stopped after {self.timeout} seconds]".encode()
        output = _ANSI.sub("", raw.decode("utf-8", errors="replace")).strip()
        return CommandResult(command, exit_code, truncate_middle(output), time.monotonic() - started)

    # ---- git (read-only, used by tools and the project list) ----

    def git(self, *args: str, timeout: int = 20) -> str | None:
        """Output of a read-only git command, or None if git isn't available or it failed."""
        if not (self.root / ".git").exists():
            return None
        try:
            completed = subprocess.run(
                ["git", *args], cwd=self.root, capture_output=True, timeout=timeout, check=False,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )  # fmt: skip
        except (OSError, subprocess.TimeoutExpired):
            return None
        if completed.returncode != 0:
            return None
        return completed.stdout.decode("utf-8", errors="replace").strip()

    def git_changes(self) -> str:
        status = self.git("status", "--short", "--branch")
        if status is None:
            raise WorkspaceError("This project isn't a git repository, so there are no tracked changes.")
        staged = self.git("diff", "--staged") or ""
        unstaged = self.git("diff") or ""
        parts = [f"git status:\n{status}"]
        if staged:
            parts.append(f"Staged changes:\n{staged}")
        if unstaged:
            parts.append(f"Unstaged changes:\n{unstaged}")
        if not staged and not unstaged:
            parts.append("No changes to tracked files.")
        return truncate_middle("\n\n".join(parts), 30_000)


def _inside(path: Path, root: Path) -> bool:
    return path == root or path.is_relative_to(root)


def _safe_iterdir(folder: Path) -> Iterator[Path]:
    try:
        yield from folder.iterdir()
    except OSError:
        return


def _write(path: Path, text: str, crlf: bool) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text.replace("\n", "\r\n") if crlf else text)


def _change(rel_path: str, old: str, new: str, created: bool) -> FileChange:
    diff_lines = list(
        difflib.unified_diff(old.splitlines(), new.splitlines(), f"a/{rel_path}", f"b/{rel_path}", lineterm="", n=3)
    )
    added = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))
    if len(diff_lines) > MAX_DIFF_LINES:
        diff_lines = [*diff_lines[:MAX_DIFF_LINES], f"... {len(diff_lines) - MAX_DIFF_LINES} more diff lines"]
    return FileChange(rel_path, created, added, removed, "\n".join(diff_lines))


# ---- the project list ----

RESERVED_IDS = frozenset({"scratch"})  # the memory scope for chats without a project
_GIT_URL = re.compile(r"^https://[A-Za-z0-9.-]+(:\d+)?/[A-Za-z0-9._~/-]+$")


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40].strip("-")
    return slug or "project"


class ProjectRegistry:
    """The projects are the sub-folders of the workspace root. The list is read from disk on every call,
    so a folder copied in by hand appears without a restart."""

    def __init__(self, root: Path, allowlist: frozenset[str] = frozenset(), timeout: int = 180):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._allowlist = allowlist
        self._timeout = timeout

    def list(self) -> list[Project]:
        projects: list[Project] = []
        taken: set[str] = set(RESERVED_IDS)
        for entry in sorted(_safe_iterdir(self.root), key=lambda p: p.name.lower()):
            if not entry.is_dir() or entry.name.startswith(".") or entry.name in IGNORED_DIRS:
                continue
            base = slugify(entry.name)
            project_id, n = base, 2
            while project_id in taken:
                project_id, n = f"{base[:37]}-{n}", n + 1
            taken.add(project_id)
            projects.append(Project(project_id, entry.name, entry, (entry / ".git").exists()))
        return projects

    def get(self, project_id: str) -> Project | None:
        return next((p for p in self.list() if p.id == project_id), None)

    def workspace(self, project: Project) -> Workspace:
        return Workspace(project.path, self._allowlist, self._timeout)

    def clone(self, url: str, name: str | None = None) -> Project:
        url = url.strip()
        if not _GIT_URL.match(url):
            raise WorkspaceError("Use an https:// git URL, like https://github.com/owner/repo.git")
        folder = (name or url.rstrip("/").split("/")[-1].removesuffix(".git")).strip()
        if not re.fullmatch(r"[A-Za-z0-9._ -]{1,60}", folder) or folder.startswith("."):
            raise WorkspaceError("Use a folder name made of letters, numbers, spaces, dots, dashes or underscores.")
        target = self.root / folder
        if target.exists():
            raise WorkspaceError(f"A folder called '{folder}' already exists in the workspace.")
        try:
            completed = subprocess.run(
                ["git", "clone", "--depth", "50", "--", url, str(target)],
                capture_output=True, timeout=300, check=False, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )  # fmt: skip
        except FileNotFoundError as exc:
            raise WorkspaceError("git isn't installed on the CodeLoop server.") from exc
        except subprocess.TimeoutExpired as exc:
            shutil.rmtree(target, ignore_errors=True)
            raise WorkspaceError("Cloning took longer than 5 minutes and was stopped.") from exc
        if completed.returncode != 0:
            shutil.rmtree(target, ignore_errors=True)
            message = completed.stderr.decode("utf-8", errors="replace").strip().splitlines()
            raise WorkspaceError(f"git clone failed: {message[-1] if message else 'unknown error'}")
        project = next((p for p in self.list() if p.path == target.resolve()), None)
        if project is None:
            raise WorkspaceError("The repository was cloned but couldn't be opened.")
        return project
