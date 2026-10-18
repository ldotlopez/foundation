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

1. **`Cache`** exposes `set`, `get`, `delete`, `iter`, and `prune`; `prune`
   also runs the backend's `cleanup()`.
2. **`BaseStorage`** is a `Protocol` defining byte storage, metadata,
   `cleanup()`, `claim_maintenance()`, and `close()` operations.
3. **`Validator`** decides whether one entry is still valid; an optional
   **`EvictionPolicy`** selects entries to remove from the valid population
   when cache-wide limits are exceeded.

The cache does not encode values. Callers provide bytes and are responsible for
serialization, for example with `foundation.jsonlib`. The storage backends
implement the same byte key-value contract:

| Backend | Persistence and layout | Metadata/access behavior |
| --- | --- | --- |
| `DiskStorage` | One file per safe key, sharded by the first two key characters, plus a SQLite metadata sidecar beneath `base_dir` | Records creation, modification, access times, and logical size in the index, which is the source of truth; files without an index row are ignored |
| `KeyHashStorage` | One file per SHA-256 key digest under `base_dir`, plus a SQLite key/metadata index | Preserves original keys in the index; supports arbitrary key strings |
| `ValueHashStorage` | One file per SHA-256 value digest under `base_dir`, plus a SQLite key/metadata index | Deduplicates equal values; metadata and access times are per key |
| `SqliteStorage` | SQLite table (through `dblib.SQLite3DB`, so WAL for files) stores one value and metadata row per key; an omitted `db_path` selects an in-memory database | Stores creation, modification, last-access time, and logical byte size; reads update access time in one SQL statement |

`DiskStorage` keys are validated as safe single path components. The hashed
file stores and SQLite accept keys as-is; the hashed stores use SHA-256 only
for filenames and retain the original key in SQLite. Every backend implements
`close()` to release its SQLite connection; call it when finished. The
in-memory `SqliteStorage` database loses its contents when that connection is
closed.

`StorageEntryMetadata` is the minimal storage-owned protocol and requires only
the original `key`. Optional metadata capabilities are represented separately
by `HasCreatedTime`, `HasModifiedTime`, `HasLastAccessTime`, and `HasSize`.
Each backend returns its own metadata object and may expose any combination of
those capabilities. The current built-in backends happen to expose all four:
overwrites preserve `created_at` and refresh `modified_at`; reads through
`get()` or `get_with_metadata()` refresh `last_access_time`, while
`get_metadata()` is pure inspection and does not; `size` is logical value size.
`get_with_metadata()` is the canonical read and `get()` wraps it.

Cache validators and eviction policies declare the metadata capabilities they
require. For example, `TTLValidator` requires `HasModifiedTime`, LRU entry
eviction requires `HasLastAccessTime`, and size-based eviction requires both
`HasLastAccessTime` and `HasSize`. Choosing compatible backends, validators,
and policies is the caller's responsibility; using a capability that a
backend does not provide raises `TypeError` when the validator or policy is
run.

The file-backed stores coordinate content and SQLite metadata with best-effort
operation ordering, not a cross-resource transaction. They write content
before metadata and delete metadata before content. An interrupted new write
can leave an unindexed file; an interrupted key-hash overwrite can leave new
content with old metadata because that store reuses the same key-derived path.
In `ValueHashStorage`, deleting or replacing a key removes its old blob only
after no remaining key references it. Content that is missing, or fails
`ValueHashStorage`'s digest check, cannot be recovered: the store deletes the
entry when it notices and reports it as absent with `EntryNotFoundError`
(`get_metadata()` notices only in `DiskStorage`, which stats the file). A
damaged shared object goes once its last key is dropped, and writing the same
value again to `ValueHashStorage` rewrites it. These stores do not provide
concurrent-writer coordination. Deleting the last file in a shard directory
removes the directory; `set()` recreates it once if a concurrent delete removes
it mid-write. `cleanup()` removes empty shard directories left behind anyway in
every file-backed store; in the hashed stores it also removes object files no
index row references (orphans and leftover temp files), but only once they
are older than a five-minute grace period, so it is safe alongside `set()` in
other processes. `DiskStorage.cleanup()` never removes unindexed
files.

Periodic maintenance has one scheduler. Every backend implements
`claim_maintenance(interval)`, which returns true when at least `interval`
seconds have passed since the last claimed run and records the new run. The
time lives in a single-row `maintenance_clock` table in the backend's SQLite
database (the metadata index for file-backed stores), and one atomic `UPDATE`
claims each run, so only one of several concurrent callers gets it. A new
clock starts at creation time, so a fresh store needs no maintenance. The
caller performs the run: `Cache` prunes, and a storage user without a cache
calls `cleanup()`.

`cleanup()` remains backend maintenance, not cache pruning. Beyond removing
unreferenced hashed objects, it does not scan for entries with lost content;
reads drop those as described above.

### Cache operations and limits

- A cache miss is translated from `EntryNotFoundError` into `MissingKeyError`;
  entries whose content storage could not recover are misses too.
- `Cache.close()` closes the underlying storage; `Cache` is also a context
  manager that closes on exit without pruning.
- `get()` reads the value and metadata together, touching access time. If
  validation fails, it deletes the entry and raises `ExpiredKeyError`.
- Validators and eviction policies consume the specific storage metadata
  capabilities they require.
- `prune()` scans for invalid entries and then applies the optional eviction
  policy to valid entries, then runs the backend's `cleanup()` with the same
  `dry_run`. It returns a `PruneReport`: metadata for removed entries and the
  paths `cleanup()` removed. A dry run reports the same entries without
  deleting them, but its cleanup paths cannot include files that those
  deletions would free; entries with lost content are still dropped, as they
  hold no data.
- `prune()` runs when the application calls it, or when the cache opens with
  `prune_interval` set and `claim_maintenance(prune_interval)` succeeds.
  Eviction policies apply only when pruning, so they do not enforce a hard
  limit on every write. With no policy, there is no capacity enforcement.
- The built-in eviction policies use least-recently-accessed ordering. Access
  is recorded by `Cache.get()` and by the storage's `get()` and
  `get_with_metadata()`; `get_metadata()` does not record an access.

Pruning is best-effort and is not synchronized with concurrent cache operations
or other processes using the same storage. Storage provides no cache-eviction
locking or transaction guarantees.

`UserCache` is a specialization that derives a per-user cache directory via
`platformdirs` and uses `TTLValidator`. It stores entries in `KeyHashStorage`,
so any string is a valid key, inside an `entries` subdirectory with owner-only
permissions; the app directory itself, or a caller-provided `base_dir`, is left
untouched, so cleanup never removes the app's own files or directories. Its
`app` name must be a safe path component. It has no eviction policy and is
hands-off: it sets `prune_interval` to its `expiration_time` (24 hours by
default), so opening it
prunes once per expiration period and entries written before one prune have
expired by the next.

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
  cursors, a transaction context manager, and explicit connection closing. It
  enables foreign keys, a 5-second busy timeout, WAL journaling, NORMAL
  synchronous mode, and in-memory temporary storage. WAL improves reader/writer
  coexistence; NORMAL can lose recent committed transactions on power loss
  while preserving database consistency. Use SQLite's backup API while the
  database is open instead of copying only its main file. It is used by
  file-backed storage indexes and `SqliteStorage`, but is not itself a storage
  backend.
- **`app.Application`** is a minimal example that stores a name and prints a
  greeting; it is not a lifecycle or dependency-management framework.

## Packaging and dependencies

The package targets Python 3.13+. Core dependencies are `click`,
`platformdirs`, and `rich`, used by the CLI/logging and storage/cache modules.
The `scraping` optional dependency group declares `bs4`, `html5lib`,
`markdownify`, `readability-lxml`, and `trafilatura`; `html5lib` is the parser
selected by `scrapelib.soupify()`.
