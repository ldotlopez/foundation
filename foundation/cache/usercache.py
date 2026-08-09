from __future__ import annotations

from pathlib import Path

import platformdirs

from ..storage import DiskStorage, validate_path_component
from .cache import Cache
from .validation import TTLValidator

# Owner-only. UserCache lives in a per-user, per-app location by
# default; nothing else on the machine should be able to read or
# write it. Chosen here, in the cache layer, and passed down to
# DiskStorage — DiskStorage itself has no opinion on permissions.
_USER_CACHE_DIR_MODE = 0o700


class UserCache(Cache):
    """Disk-backed cache rooted at the platform's per-user cache
    directory for `app`, with time-based expiration.

        cache = UserCache(app="foo", expiration_time=3600)

    Note: like Cache in general, this assumes no concurrent threads
    or processes mutate the same storage directory concurrently (see
    Cache.get's docstring). A per-app user cache directory is exactly
    the kind of location two independent invocations of the same
    tool might share, so that assumption is worth being aware of
    here in particular, even though it's not enforced yet.
    """

    def __init__(
        self,
        app: str,
        expiration_time: float,
        base_dir: Path | None = None,
    ) -> None:
        """
        Args:
            app: Application name; used to derive the platform user
                cache directory (e.g. ~/.cache/{app} on Linux). Must
                be a single safe path segment - no separators or `..`.
            expiration_time: Seconds after which an entry is treated
                as expired (see TTLValidator).
            base_dir: Overrides the platform-derived directory
                entirely, e.g. for tests. When omitted, the platform
                user cache directory for `app` is used.
        """
        validate_path_component(app)

        resolved_dir = base_dir or Path(platformdirs.user_cache_dir(app))
        storage = DiskStorage(base_dir=resolved_dir, dir_mode=_USER_CACHE_DIR_MODE)

        super().__init__(storage=storage, validator=TTLValidator(expiration_time))
