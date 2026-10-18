# foundation

`foundation` is a Python library of reusable building blocks for applications and
services. It currently provides cache and storage backends, plugin loading,
logging and CLI helpers, plus small utilities for JSON, dates, text, and HTML
content.

## Requirements and installation

- Python 3.13 or newer
- Install from a checkout with `pip install .`

The `scraping` extra enables the declared HTML/content dependencies:

```sh
pip install ".[scraping]"
```

The core dependencies (`click`, `platformdirs`, and `rich`) support
the storage/cache, user-cache, and logging/CLI modules. The `scraping` extra
installs the additional HTML/content libraries (`bs4`, `html5lib`,
`markdownify`, `readability-lxml`, and `trafilatura`).

## Quick start

The cache API combines a storage backend with entry validation and optional
capacity-based eviction:

```python
from foundation.cache import Cache, MaxEntriesEvictionPolicy
from foundation.storage import DiskStorage

cache = Cache(
    storage=DiskStorage(),
    eviction_policy=MaxEntriesEvictionPolicy(max_entries=500),
)
cache.set("greeting", b"hello")
print(cache.get("greeting").decode("utf-8"))
```

Disk storage shards entries into directories beneath its `base_dir`. If omitted,
it creates a temporary directory, which `close()` removes. For a persistent SQLite-backed cache, pass
`SqliteStorage` instead:

```python
from pathlib import Path

from foundation.cache import Cache
from foundation.storage import SqliteStorage

cache = Cache(storage=SqliteStorage(Path("var/cache.sqlite3")))
cache.set("greeting", b"hello")
try:
    print(cache.get("greeting").decode("utf-8"))
finally:
    cache.close()
```

`Cache.get()` raises `MissingKeyError` for a missing entry and
`ExpiredKeyError` when its validator rejects an entry. The default validator
accepts entries without expiration. `TTLValidator` checks age since modification;
`UserCache` applies a TTL and stores data in an `entries` subdirectory of the
platform's per-user cache directory, accepting any string as a key. It is
hands-off: opening it prunes expired entries once per expiration period.

```python
from foundation.cache import UserCache

with UserCache(app="myapp", expiration_time=3600) as cache:
    cache.set("https://example.com/", b"<html>...</html>")
```

Validators and eviction policies use structural metadata protocols and check
compatibility when they receive an entry. Call `cache.prune()` when it suits
the application, or pass `prune_interval` (seconds) to prune on open once that
much time has passed since the last prune, by any process. Eviction policies
apply only when pruning. Pruning is best-effort and is not synchronized across
concurrent cache users; it also runs the storage's `cleanup()`. To clean up a
storage used without a cache, claim a run from its persisted clock:
`if storage.claim_maintenance(86400): storage.cleanup()`.

## Package overview

| Module | Purpose |
| --- | --- |
| `foundation.cache` | Cache facade, TTL validation, LRU eviction, and per-user cache |
| `foundation.storage` | Storage protocol, file-backed (`DiskStorage`, `KeyHashStorage`, `ValueHashStorage`) and SQLite backends |
| `foundation.plugin` | Lazy module/class loading and Protocol-aware plugin registration |
| `foundation.loglib`, `foundation.clilib` | Python logging setup, Rich consoles, and reusable Click logging options |
| `foundation.scrapelib` | HTML parsing, DOM cleanup, content extraction, and Markdown conversion |
| `foundation.jsonlib` | JSON encoding/decoding for datetimes and sets |
| `foundation.dtlib` | UTC/local timestamps and timezone-aware datetime conversion |
| `foundation.textlib` | Text slugification |
| `foundation.dblib` | Minimal SQLite connection/transaction helper |
| `foundation.app` | Minimal `Application` example class |

Only `Application` is re-exported from the top-level `foundation` package.
Other APIs are imported from their modules or subpackages, as in the examples
above.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for package structure, component
contracts, and operational details.

## Development

The project uses `uv`; its development dependency group is declared in
`pyproject.toml`. Run `uv sync --group dev` to install the project and that
group in a local environment. Run the tests with
`uv run python -m unittest discover -s tests`.
