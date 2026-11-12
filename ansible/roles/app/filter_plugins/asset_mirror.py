"""Prune plan of the deployment asset mirror (tasks/assets.yml).

A deployed path is deleted only when Ansible could have put it there: it is
absent from the checkout and was tracked in this repository's git history
under the same path. Anything else the checkout lacks (manual backups made on
the server, generated files) is kept and reported.
"""

import posixpath


def _excluded(path, excludes):
    return any(path == prefix or path.startswith(prefix.rstrip("/") + "/") for prefix in excludes)


def asset_mirror_plan(deployed, source, history, excludes=()):
    """Return {'stale': [...], 'untracked': [...]} for paths relative to the app/repo roots.

    deployed: files and directories under the copied directories on the server.
    source: files and directories under the same directories in the checkout.
    history: files ever tracked under those directories (git log --all --name-only).
    """
    source = set(source)
    history_files = {path for path in history if path}
    history_dirs = set()
    for path in history_files:
        parent = posixpath.dirname(path)
        while parent:
            history_dirs.add(parent)
            parent = posixpath.dirname(parent)

    candidates = sorted({path for path in deployed if path not in source and not _excluded(path, excludes)})
    untracked = [path for path in candidates if path not in history_files and path not in history_dirs]
    stale = [path for path in candidates if path in history_files]
    # A directory goes only when it held tracked files and nothing untracked remains below it.
    stale += [path for path in candidates
              if path in history_dirs and not any(other.startswith(path + "/") for other in untracked)]
    return {"stale": sorted(stale), "untracked": untracked}


class FilterModule:
    def filters(self):
        return {"asset_mirror_plan": asset_mirror_plan}
