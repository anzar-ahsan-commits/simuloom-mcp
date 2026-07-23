from __future__ import annotations

import io
import zipfile
from pathlib import Path, PurePosixPath

from simuloom.models import WorkspaceRestoreResult

MAX_WORKSPACE_BACKUP_SIZE = 50 * 1024 * 1024
MAX_WORKSPACE_BACKUP_FILES = 10_000
WORKSPACE_CONTROL_FILES = {".workspace.lock", ".simuloom-workspace.json"}


def create_workspace_backup(root: Path) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            relative = path.relative_to(root).as_posix()
            if (
                relative in WORKSPACE_CONTROL_FILES
                or relative.startswith("audit/")
                or relative.startswith("runtime/")
            ):
                continue
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, path.read_bytes())
    data = output.getvalue()
    if len(data) > MAX_WORKSPACE_BACKUP_SIZE:
        raise ValueError("Workspace backup exceeds the 50 MiB limit")
    return data


def restore_workspace_backup(root: Path, data: bytes) -> WorkspaceRestoreResult:
    if len(data) > MAX_WORKSPACE_BACKUP_SIZE:
        raise ValueError("Workspace backup exceeds the 50 MiB limit")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError("Workspace backup is not a valid ZIP archive") from exc
    with archive:
        files = [item for item in archive.infolist() if not item.is_dir()]
        if len(files) > MAX_WORKSPACE_BACKUP_FILES:
            raise ValueError("Workspace backup contains too many files")
        total = sum(item.file_size for item in files)
        if total > MAX_WORKSPACE_BACKUP_SIZE:
            raise ValueError("Expanded workspace backup exceeds the 50 MiB limit")
        targets: list[tuple[zipfile.ZipInfo, Path]] = []
        target_paths: set[Path] = set()
        for item in files:
            relative = PurePosixPath(item.filename)
            if relative.is_absolute() or ".." in relative.parts or not relative.parts:
                raise ValueError(f"Unsafe workspace backup path: {item.filename}")
            if (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Workspace backup cannot contain symbolic links")
            target = root.joinpath(*relative.parts)
            if target in target_paths:
                raise ValueError(f"Workspace backup contains a duplicate path: {item.filename}")
            target_paths.add(target)
            if target.exists():
                raise ValueError(f"Workspace restore would overwrite: {item.filename}")
            targets.append((item, target))
        for item, target in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(item))
    return WorkspaceRestoreResult(restored_files=len(files), restored_bytes=total)
