import tempfile
from collections.abc import Collection
from os import stat_result
from pathlib import Path

from ._base import StorageCorruptionError


def atomic_write(path: Path, value: bytes) -> None:
    """Write value to path through a sibling temp file and a rename.

    The parent directory must already exist.
    """
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
        try:
            temporary.write(value)
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise
    try:
        temporary_path.replace(path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def read_backing_file(key: str, path: Path) -> bytes:
    """Read the file backing an indexed key."""
    try:
        return path.read_bytes()
    except FileNotFoundError as error:
        raise StorageCorruptionError(
            key, f"backing file {path.name!r} is missing"
        ) from error


def stat_backing_file(key: str, path: Path) -> stat_result:
    """Stat the file backing an indexed key."""
    try:
        return path.stat()
    except FileNotFoundError as error:
        raise StorageCorruptionError(
            key, f"backing file {path.name!r} is missing"
        ) from error


def remove_empty_shard_dirs(
    root: Path, *, dry_run: bool, removed_paths: Collection[str] = ()
) -> list[str]:
    """Remove empty directories directly under root and return their paths.

    Children listed in removed_paths count as gone, so a dry run reports
    directories that the real run would empty first.
    """
    removed: list[str] = []
    for shard_dir in sorted(root.iterdir()):
        if not shard_dir.is_dir():
            continue
        try:
            if any(str(child) not in removed_paths for child in shard_dir.iterdir()):
                continue
            if not dry_run:
                shard_dir.rmdir()
        except FileNotFoundError:
            continue
        removed.append(str(shard_dir))
    return removed
