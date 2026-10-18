from pathlib import Path

import platformdirs

from ..storage import KeyHashStorage, validate_path_component
from .cache import Cache
from .validation import TTLValidator

# Owner-only. UserCache lives in a per-user, per-app location by
# default; nothing else on the machine should be able to read or
# write it. Chosen here, in the cache layer; storage itself has no
# opinion on permissions.
_USER_CACHE_DIR_MODE = 0o700

_DEFAULT_EXPIRATION_TIME = 24 * 60 * 60


class UserCache(Cache):
    """Disk-backed cache in the platform's per-user cache directory for
    `app`, with time-based expiration.

        cache = UserCache(app="foo")

    Entries live in an owner-only `entries` subdirectory, so the app can
    keep its own files beside them. Any string is a valid key.

    Hands-off: opening the cache prunes it once expiration_time has
    passed since the last prune, so entries written before one prune
    have expired by the next. Pruning is best-effort and is not
    synchronized with concurrent processes using the same directory.
    """

    def __init__(
        self,
        app: str,
        expiration_time: float = _DEFAULT_EXPIRATION_TIME,
        base_dir: Path | None = None,
    ) -> None:
        """
        Args:
            app: Application name; used to derive the platform user
                cache directory (e.g. ~/.cache/{app} on Linux). Must
                be a single safe path segment - no separators or `..`.
            expiration_time: Seconds after which an entry is treated
                as expired (see TTLValidator). Defaults to 24 hours.
            base_dir: Overrides the platform-derived directory
                entirely, e.g. for tests. Entries are stored in its
                `entries` subdirectory; base_dir itself is not changed.
        """
        validate_path_component(app)

        if base_dir is None:
            base_dir = Path(platformdirs.user_cache_dir(app))
        entries_dir = base_dir / "entries"
        entries_dir.mkdir(parents=True, exist_ok=True)
        # mkdir's mode is masked by the umask; chmod sets the exact bits.
        entries_dir.chmod(_USER_CACHE_DIR_MODE)

        super().__init__(
            storage=KeyHashStorage(entries_dir),
            validator=TTLValidator(expiration_time),
            prune_interval=expiration_time,
        )
