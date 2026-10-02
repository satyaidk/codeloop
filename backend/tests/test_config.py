"""Settings find the repository's .env and workspace whichever folder the server is started from."""

from pathlib import Path

from app.config import ROOT
from tests.conftest import isolated_settings


def test_root_is_the_repository_folder_holding_backend_and_frontend():
    assert (ROOT / "backend" / "app" / "config.py").is_file()
    assert (ROOT / "frontend").is_dir()


def test_relative_workspace_paths_are_relative_to_the_repository_root(monkeypatch):
    monkeypatch.delenv("CODELOOP_WORKSPACE_ROOT", raising=False)  # e.g. set by the Docker image
    assert isolated_settings().workspace_root == ROOT / "workspace"
    assert isolated_settings(workspace_root="./my-repos").workspace_root == ROOT / "my-repos"


def test_absolute_workspace_paths_are_kept(tmp_path: Path):
    assert isolated_settings(workspace_root=tmp_path).workspace_root == tmp_path
