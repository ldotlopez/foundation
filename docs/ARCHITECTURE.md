# Architecture

## Project shape

`foundation` is a small library rather than an application framework. Its
subpackages are independent building blocks, with the cache and storage
packages forming the most integrated subsystem. There is no central service
container or shared configuration layer.

The top-level `foundation` package exports only `Application`. Consumers
import the other features from their defining modules, for example
`foundation.cache`, `foundation.storage`, or `foundation.plugin`.

```text
foundation/
+-- cache/       Cache facade, validation, eviction, user cache
+-- storage/     Storage contract, disk and SQLite implementations
+-- plugin.py    Module/class loaders and plugin registry
+-- loglib.py    Python logging setup with Rich integration
+-- clilib.py    Click options and Rich console factories
+-- *lib.py      JSON, date/time, text, database, and scraping helpers
```

## Cache and storage

The cache is composed from three roles:

1. **`Cache`** exposes `set`, `get`, `delete`, `iter`, and `prune`.
2. **`BaseStorage`** defines byte storage and metadata operations.
3. **`Validator`** decides whether one entry is still valid; an optional
   **`EvictionPolicy`** selects entries to remove from the valid population
   when cache-wide limits are exceeded.

The cache does not encode values. Callers provide bytes and are responsible for
serialization, for example with `foundation.jsonlib`. `DiskStorage` and
`SqliteStorage` implement the same storage contract:

| Backend | Persistence and layout | Metadata/access behavior |
| --- | --- | --- |
| `DiskStorage` | One file per key, sharded by the first two key characters beneath `base_dir`; defaults to a temporary directory | Uses filesystem timestamps and size; `get_with_metadata()` explicitly updates access time |
| `SqliteStorage` | SQLite table with one row per key; an omitted `db_path` selects an in-memory database | Stores modification time, last-access time, and byte size; `get_with_metadata()` updates access time in one SQL statement |

Disk keys are validated as safe single path components. SQLite keys are SQL
values and are stored as-is. `SqliteStorage.close()` releases its connection;
the in-memory database loses its contents when that connection is closed.

`StorageEntryMetadata` is the backend-neutral metadata base. Backends extend
it with the properties relevant to cache behavior: `modified_at` for
`TTLValidator`, `last_access_time` for LRU policies, and `size` for
`SizeEvictionPolicy`. The cache policies consume structural protocols rather
than depending directly on a particular backend's metadata class.

### Cache operations and limits

- A cache miss is translated from `EntryNotFoundError` into `MissingKeyError`.
- `get()` reads the value and metadata together, touching access time where
  the backend supports it. If validation fails, it deletes the entry and raises
  `ExpiredKeyError`.
- Validators and eviction policies use structural metadata protocols and check
  compatibility when they receive an entry.
- `prune()` scans for invalid entries and then applies the optional eviction
  policy to valid entries. It returns metadata for entries removed or selected
  for removal during a dry run.
- Setting an eviction policy does not enforce a hard limit on every write.
  `Cache.set()` triggers pruning every `eviction_check_interval` writes;
  callers may invoke `prune()` explicitly. With no policy, there is no
  capacity enforcement.
- The built-in eviction policies use least-recently-accessed ordering. Access
  tracking is meaningful for reads through `Cache.get()`; reads directly
  through a storage backend bypass it.

Pruning is best-effort and is not synchronized with concurrent cache operations
or other processes using the same storage. Storage provides no cache-eviction
locking or transaction guarantees. Backend maintenance such as removing empty
disk shard directories remains separate from cache pruning.

`UserCache` is a specialization that derives a per-user cache directory via
`platformdirs`, requests owner-only directory permissions, and uses
`TTLValidator`. Its `app` name must be a safe path component.

## Plugin loading

`foundation.plugin` builds a staged API from low-level loading to object
discovery:

```text
ModuleLoader -> ClassLoader -> BaseRegister -> Register
```

- `ModuleLoader` imports modules by short name from a dotted namespace package;
  `discover()` lists modules directly in that namespace (not recursively).
- `ClassLoader` resolves a named class from a loaded module and can instantiate
  it.
- `BaseRegister` calls a module's configured entry-point function and stores
  its return value by module name. Registration writes only after import and
  entry-point execution succeed; duplicate names raise an error.
- `Register` adds Protocol-based querying. Each entry point returns
  `(name, protocol, object)` triples. Protocols used for queries must be
  `@runtime_checkable`. Results are queryable by protocol, plugin name, and
  object name.
- `Lazy` wraps a zero-argument factory in an entry-point result so construction
  happens at first query and the resolved object is reused.

Plugin failures are represented by `PluginError` subclasses. A targeted lookup
raises for its failure; broad protocol queries can skip entries that fail
conformance or lazy resolution and retain those failures for inspection.
`register_all()` is best-effort for plugin failures but still raises on
duplicate registration.

## Logging and command-line helpers

`setup_logger()` configures a Python logger's level from an integer, a level
specification, or an environment variable derived from the logger name.
`setup_logger_from_cmdline()` and `setup_logger_from_click()` apply conventional
verbosity and quiet counts. Specs can set the app logger level and override
individual logger levels.

With its default `infect=True`, logging setup attaches a Rich handler to the
Python root logger if one is not already present. This is a process-wide logging
side effect; pass `infect=False` when another component owns handler
configuration. `clilib` supplies shared stdout/stderr Rich consoles and reusable
Click logging flags.

## Utility modules

- **`jsonlib`** handles JSON-compatible primitives and tags datetimes and sets
  so they can be reconstructed by its paired decoder.
- **`dtlib`** provides UTC/local timestamps and converts epoch timestamps into
  timezone-aware datetimes.
- **`textlib`** replaces each non-ASCII-alphanumeric character in a string with
  a chosen separator; it does not collapse repeated separators.
- **`scrapelib`** parses HTML with Beautiful Soup, extracts content with
  Trafilatura, converts HTML to Markdown, and provides DOM/meta-tag helpers.
- **`dblib.SQLite3DB`** is a separate lightweight SQLite helper that exposes
  cursors and a transaction context manager. It is not the cache storage
  backend.
- **`app.Application`** is a minimal example that stores a name and prints a
  greeting; it is not a lifecycle or dependency-management framework.

## Packaging and dependencies

The package targets Python 3.13+. Core dependencies are `click`,
`platformdirs`, and `rich`, used by the CLI/logging and storage/cache modules.
The `scraping` optional dependency group declares `bs4`, `html5lib`,
`markdownify`, `readability-lxml`, and `trafilatura`; `html5lib` is the parser
selected by `scrapelib.soupify()`.
