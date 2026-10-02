"""The workspace is the agent's safety boundary, so it's tested directly."""

import os
import sys

import pytest

from app.workspace import ProjectRegistry, Workspace, WorkspaceError, is_secret, slugify, truncate_middle


@pytest.mark.parametrize("bad", ["../other", "src/../../other", "..\\other"])
def test_paths_cannot_escape_the_project(workspace, bad):
    with pytest.raises(WorkspaceError, match="outside the project"):
        workspace.resolve(bad)


def test_rooted_paths_are_read_as_project_relative(workspace, project_dir):
    assert workspace.resolve("/src/cart.py") == (project_dir / "src" / "cart.py").resolve()


def test_absolute_path_outside_the_project_is_refused(workspace, tmp_path):
    with pytest.raises(WorkspaceError):
        workspace.resolve(str(tmp_path / "elsewhere.txt"))


@pytest.mark.parametrize(
    "name,secret",
    [(".env", True), (".env.production", True), (".env.example", False), ("id_rsa", True), ("server.pem", True),
     ("config.py", False), ("README.md", False)],
)  # fmt: skip
def test_secret_files_are_recognised(name, secret):
    assert is_secret(f"some/dir/{name}") is secret


def test_secret_files_cannot_be_read_or_written(workspace):
    with pytest.raises(WorkspaceError, match="secrets"):
        workspace.read(".env")
    with pytest.raises(WorkspaceError, match="secrets"):
        workspace.write(".env", "X=1")


def test_read_numbers_lines_and_pages(workspace):
    text, rel, summary = workspace.read("src/cart.py", start_line=2, end_line=2)

    assert rel == "src/cart.py"
    assert "2 |     return sum" in text
    assert "def total" not in text
    assert "lines 2-2 of 6" in text
    assert "start_line=3" in text  # tells the model how to continue
    assert summary == "Read src/cart.py · lines 2–2 of 6"


def test_read_missing_file_explains(workspace):
    with pytest.raises(WorkspaceError, match="doesn't exist"):
        workspace.read("src/nope.py")


def test_list_tree_skips_dependency_folders(workspace):
    text, count = workspace.list_tree(".", depth=3)

    assert "src/" in text and "cart.py" in text
    assert "node_modules" not in text
    assert count > 0


def test_search_finds_lines_and_skips_secrets_and_dependencies(workspace):
    text, total = workspace.search("sk_live|total|module.exports")

    assert "src/cart.py:1: def total(items):" in text
    assert "tests/test_cart.py" in text
    assert "sk_live" not in text  # .env is never searched
    assert "left-pad" not in text
    assert total == 4


def test_search_with_invalid_regex_falls_back_to_plain_text(workspace):
    text, total = workspace.search("['qty'")  # an unclosed [ is not a valid regex
    assert total == 1 and "src/cart.py:2:" in text


def test_edit_replaces_one_exact_match_and_returns_a_diff(workspace, project_dir):
    change = workspace.edit("src/cart.py", "    return []", "    return list()")

    assert "return list()" in (project_dir / "src" / "cart.py").read_text()
    assert (change.added, change.removed) == (1, 1)
    assert "-    return []" in change.diff and "+    return list()" in change.diff


def test_edit_explains_missing_and_ambiguous_text(workspace):
    with pytest.raises(WorkspaceError, match="not found"):
        workspace.edit("src/cart.py", "nothing like this", "x")
    with pytest.raises(WorkspaceError, match="appears 2 times"):
        workspace.edit("src/cart.py", "    return", "    yield")


def test_edit_keeps_windows_line_endings(workspace, project_dir):
    path = project_dir / "src" / "win.py"
    path.write_bytes(b"a = 1\r\nb = 2\r\n")

    workspace.edit("src/win.py", "a = 1\nb = 2", "a = 1\nb = 3")

    assert path.read_bytes() == b"a = 1\r\nb = 3\r\n"


def test_write_creates_folders_and_reports_creation(workspace, project_dir):
    change = workspace.write("src/new/util.py", "def f():\n    return 1\n")

    assert (project_dir / "src" / "new" / "util.py").exists()
    assert change.created is True and change.added == 2


def test_writes_into_git_or_dependency_folders_are_refused(workspace):
    for path in (".git/config", "node_modules/x.js"):
        with pytest.raises(WorkspaceError):
            workspace.write(path, "x")


@pytest.mark.parametrize(
    "command,message",
    [
        ("rm -rf /", "isn't on the list"),
        ("python -c 1 && rm x", "one command at a time"),
        ("pytest | tee out", "one command at a time"),
        ("git push origin main", "read-only git"),
        ("git reset --hard", "read-only git"),
        ("", "empty"),
    ],
)
def test_commands_outside_the_rules_are_refused(workspace, command, message):
    with pytest.raises(WorkspaceError, match=message):
        workspace.parse_command(command)


def test_allowed_programs_parse_with_or_without_extension(workspace):
    assert workspace.parse_command("python.exe -m pytest -q")[0] == "python.exe"
    assert workspace.parse_command("git status")[1] == "status"


def test_run_executes_in_the_project_and_hides_the_servers_keys(workspace, monkeypatch, project_dir):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("PATH", os.path.dirname(sys.executable) + os.pathsep + os.environ["PATH"])
    script = "import os; print(os.getcwd()); print(os.environ.get('OPENAI_API_KEY'))"

    result = workspace.run(f'python -c "{script}"')

    assert result.exit_code == 0
    assert str(project_dir.resolve()) in result.output
    assert "sk-should-not-leak" not in result.output
    assert result.output.strip().endswith("None")


def test_run_reports_a_timeout(project_dir, monkeypatch):
    monkeypatch.setenv("PATH", os.path.dirname(sys.executable) + os.pathsep + os.environ["PATH"])
    slow = Workspace(project_dir, frozenset({"python"}), timeout=1)

    result = slow.run('python -c "import time; time.sleep(5)"')

    assert result.exit_code is None
    assert "stopped after 1 seconds" in result.output


def test_truncate_middle_keeps_both_ends():
    text = "start " + "x" * 50_000 + " end"
    cut = truncate_middle(text, 1000)
    assert cut.startswith("start") and cut.endswith("end") and "characters cut" in cut


def test_git_changes_shows_status_and_diff(git_project):
    ws = Workspace(git_project, frozenset())
    (git_project / "src" / "cart.py").write_text("def total(items):\n    return 0\n", encoding="utf-8")

    text = ws.git_changes()

    assert "## main" in text
    assert "-    return sum" in text and "+    return 0" in text


def test_git_changes_outside_a_repo_explains(workspace):
    with pytest.raises(WorkspaceError, match="isn't a git repository"):
        workspace.git_changes()


# ---- the project registry ----


def test_registry_lists_folders_with_safe_unique_ids(tmp_path):
    for name in ("My App", "my-app", "scratch", ".hidden", "node_modules"):
        (tmp_path / name).mkdir()
    (tmp_path / "notes.txt").write_text("x")

    projects = ProjectRegistry(tmp_path).list()

    assert [(p.id, p.name) for p in projects] == [
        ("my-app", "My App"),
        ("my-app-2", "my-app"),
        ("scratch-2", "scratch"),
    ]


def test_registry_refuses_non_https_clone_urls(tmp_path):
    registry = ProjectRegistry(tmp_path)
    for url in ("file:///etc", "ext::sh -c touch% /tmp/x", "git@github.com:a/b.git", "http://example.com/x"):
        with pytest.raises(WorkspaceError, match="https://"):
            registry.clone(url)


def test_slugify():
    assert slugify("Coding Agent!") == "coding-agent"
    assert slugify("???") == "project"
