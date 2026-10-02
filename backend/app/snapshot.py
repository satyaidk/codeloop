"""'Learn this project': a one-time scan of a repository, written into its memory bank.

The scan is plain code, not an agent run: it reads the layout, manifests, build and CI files and recent
commits, and hands the result to Hindsight, which extracts facts from it in the background. It costs no
agent-model tokens, works with the smallest local model, and gives every later chat a map of the codebase
so the agent doesn't have to rediscover it.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.workspace import Workspace, WorkspaceError, is_secret

MAX_SNAPSHOT_CHARS = 16_000

# Files that say the most about a project, in the order they're included.
KEY_FILES = (
    "README.md", "README.rst", "README.txt", "README", "AGENTS.md", "CLAUDE.md", "CONTRIBUTING.md",
    "package.json", "pyproject.toml", "requirements.txt", "requirements-dev.txt", "setup.cfg", "Pipfile",
    "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "build.gradle.kts", "Gemfile", "composer.json",
    "Makefile", "justfile", "Dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yaml",
    "tsconfig.json", "vite.config.ts", "vite.config.js", "vitest.config.ts", "jest.config.js", "jest.config.ts",
    "pytest.ini", "tox.ini", "noxfile.py", ".env.example",
)  # fmt: skip
LIMITS = {"README.md": 4000, "README.rst": 4000, "README.txt": 4000, "README": 4000}
DEFAULT_LIMIT = 1800


@dataclass
class Snapshot:
    text: str
    files_scanned: int
    head: str | None
    branch: str | None


def take_snapshot(workspace: Workspace, name: str) -> Snapshot:
    files = list(workspace.walk_files())
    branch = workspace.git("rev-parse", "--abbrev-ref", "HEAD")
    head = workspace.git("rev-parse", "--short", "HEAD")
    taken = datetime.now(UTC).strftime("%Y-%m-%d")

    sections = [
        f"# Project snapshot: {name}",
        f"Scanned on {taken}" + (f" at commit {head} on branch {branch}." if head else "."),
        f"{len(files)} files (dependency and build folders excluded).",
        "## Languages (files by extension)\n" + _languages(files),
    ]
    tree, _ = workspace.list_tree(".", depth=3, limit=220)
    sections.append(f"## Layout\n```\n{tree}\n```")
    log = workspace.git("log", "-12", "--format=%h %ad %s", "--date=short")
    if log:
        sections.append(f"## Recent commits\n{log}")
    for block in _key_files(workspace):
        sections.append(block)
    for workflow in sorted((workspace.root / ".github" / "workflows").glob("*.y*ml"))[:3]:
        sections.append(_file_block(workspace, workspace.rel(workflow), DEFAULT_LIMIT))

    text = "\n\n".join(s for s in sections if s)
    if len(text) > MAX_SNAPSHOT_CHARS:
        text = text[:MAX_SNAPSHOT_CHARS] + "\n\n(snapshot cut to size)"
    return Snapshot(text=text, files_scanned=len(files), head=head, branch=branch)


def _languages(files: list[Path]) -> str:
    counts = Counter(f.suffix.lower() or f.name for f in files)
    return ", ".join(f"{ext} {n}" for ext, n in counts.most_common(12))


def _key_files(workspace: Workspace) -> list[str]:
    blocks = []
    for name in KEY_FILES:
        if (workspace.root / name).is_file():
            block = _file_block(workspace, name, LIMITS.get(name, DEFAULT_LIMIT))
            if block:
                blocks.append(block)
    return blocks


def _file_block(workspace: Workspace, rel: str, limit: int) -> str:
    try:
        _, text = workspace.read_text(rel)
    except WorkspaceError:
        return ""
    if rel.endswith("package.json"):
        text = _package_summary(text)
    elif rel.endswith(".env.example") or is_secret(rel):
        # Only the variable names: example values can still be real keys someone forgot to blank.
        names = [
            line.split("=", 1)[0].strip()
            for line in text.splitlines()
            if "=" in line and not line.lstrip().startswith("#")
        ]
        text = "Environment variables: " + ", ".join(names)
    if len(text) > limit:
        text = text[:limit] + "\n... (cut)"
    return f"## {rel}\n```\n{text.strip()}\n```"


def _package_summary(text: str) -> str:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text
    summary = {
        "name": data.get("name"),
        "type": data.get("type"),
        "scripts": data.get("scripts"),
        "dependencies": sorted(data.get("dependencies", {})),
        "devDependencies": sorted(data.get("devDependencies", {})),
        "workspaces": data.get("workspaces"),
    }
    return json.dumps({k: v for k, v in summary.items() if v}, indent=1)
