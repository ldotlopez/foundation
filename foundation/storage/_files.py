import tempfile
from collections.abc import Collection
from pathlib import Path


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


def remove_dir_if_empty(path: Path) -> None:
    """Remove path if it is an empty directory."""
    try:
        path.rmdir()
    except OSError:
        # Not empty, or already removed by someone else.
        return


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
