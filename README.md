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
it creates a temporary directory. For a persistent SQLite-backed cache, pass
`SqliteStorage` instead:

```python
from pathlib import Path

from foundation.cache import Cache
from foundation.storage import SqliteStorage

storage = SqliteStorage(Path("var/cache.sqlite3"))
cache = Cache(storage=storage)
cache.set("greeting", b"hello")
try:
    print(cache.get("greeting").decode("utf-8"))
finally:
    storage.close()
```

`Cache.get()` raises `MissingKeyError` for a missing entry and
`ExpiredKeyError` when its validator rejects an entry. The default validator
accepts entries without expiration. `TTLValidator` checks age since modification;
`UserCache` applies a TTL and stores data in the platform's per-user cache
directory.

Validators and eviction policies use structural metadata protocols and check
compatibility when they receive an entry. Pruning is best-effort and is not
synchronized across concurrent cache users.

## Package overview

| Module | Purpose |
| --- | --- |
| `foundation.cache` | Cache facade, TTL validation, LRU eviction, and per-user cache |
| `foundation.storage` | Abstract storage contract, filesystem backend, and SQLite backend |
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
group in a local environment. No test suite or test command is currently
declared in the project configuration.
