import { useState } from "react";
import { LoaderCircle } from "lucide-react";
import { Dialog } from "./Dialog";
import { api } from "../lib/api";
import { useAppState } from "../lib/AppState";
import { useServer } from "../lib/server";
import styles from "./Forms.module.css";

export function AddProjectDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { dispatch } = useAppState();
  const { info, refreshProjects } = useServer();
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checked, setChecked] = useState<string | null>(null);

  const close = () => {
    setError(null);
    setChecked(null);
    onClose();
  };

  const clone = async () => {
    setBusy(true);
    setError(null);
    try {
      const project = await api.clone(url.trim(), name.trim() || undefined);
      await refreshProjects();
      dispatch({ type: "selectProject", projectId: project.id });
      setUrl("");
      setName("");
      close();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const rescan = async () => {
    const list = await refreshProjects();
    setChecked(`${list.length} ${list.length === 1 ? "project" : "projects"} in the workspace.`);
  };

  return (
    <Dialog open={open} onClose={close} title="Add a project">
      <form
        className={styles.form}
        onSubmit={(e) => {
          e.preventDefault();
          void clone();
        }}
      >
        <div className={styles.field}>
          <label htmlFor="git-url">Clone a repository</label>
          <input
            id="git-url"
            className="input"
            type="url"
            required
            placeholder="https://github.com/owner/repo.git"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
        </div>
        <div className={styles.field}>
          <label htmlFor="folder-name">Folder name (optional)</label>
          <input
            id="folder-name"
            className="input"
            placeholder="Defaults to the repository's name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        {error && (
          <p className={styles.error} role="alert">
            {error}
          </p>
        )}
        <div className={styles.actions}>
          <button type="submit" className="btn btn-primary" disabled={busy || !url.trim()}>
            {busy && <LoaderCircle size={15} className="spin" />}
            {busy ? "Cloning…" : "Clone"}
          </button>
        </div>
      </form>

      <div className={styles.aside}>
        <h3>Or use a folder you already have</h3>
        <p>
          Every folder inside the workspace is a project. Copy or clone one into
          {info ? <code className={styles.path}>{info.workspace_root}</code> : " the workspace folder"}, then check
          again.
        </p>
        <button type="button" className="btn" onClick={rescan}>
          Check the workspace again
        </button>
        {checked && <p className={styles.note}>{checked}</p>}
      </div>
    </Dialog>
  );
}
