from pathlib import Path

from simuloom.core.locking import exclusive_file_lock


def test_exclusive_file_lock_creates_and_releases_lock_file(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "workspace.lock"

    with exclusive_file_lock(path):
        assert path.exists()

    with exclusive_file_lock(path):
        assert path.is_file()
