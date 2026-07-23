from __future__ import annotations

import os
import sys
from pathlib import Path

APP_UID = 10001
APP_GID = 10001


def _prepare_workspace(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for root, directories, files in os.walk(path):
        os.chown(root, APP_UID, APP_GID)
        for name in [*directories, *files]:
            target = Path(root) / name
            if not target.is_symlink():
                os.chown(target, APP_UID, APP_GID)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("A container command is required")
    if os.geteuid() == 0:
        workspace = Path(os.environ.get("SIMULOOM_WORKSPACE", "/app/workspace")).resolve()
        if workspace != Path("/app/workspace") and not workspace.is_relative_to(Path("/app")):
            raise SystemExit("Container workspace must remain within /app")
        _prepare_workspace(workspace)
        os.setgroups([])
        os.setgid(APP_GID)
        os.setuid(APP_UID)
    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == "__main__":
    main()
