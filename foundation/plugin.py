"""
Layered plugin loader system.

Layers (each built on top of the previous):
    ModuleLoader -> ClassLoader -> BaseRegister -> Register

Design decisions:
  - Namespace validation is lazy: nothing is imported until .load()/.get_class()/
    .register() is actually called.
  - All failures surface as PluginError subclasses, never raw ImportError/
    AttributeError, so callers can catch broadly (PluginError) or narrowly.
  - BaseRegister.register() is transactional by construction: the module is
    loaded and the entry point is called *before* anything is written to the
    internal store, so a failure at any step leaves the registry untouched.
  - BaseRegister does no shape validation on what the entry point returns —
    it's stored as-is, keyed by module name. This is the class to use (or
    subclass further) if you need unconstrained storage.
  - Duplicate register() calls for the same key raise; no silent overwrite.
  - Register (the Protocol-aware default most applications want) requires its
    entry points to return list[tuple[name, Protocol, object]] triples, so
    that objects can be queried by the application Protocol they implement,
    disambiguated by a per-plugin object name. See its class docstring.
  - ModuleLoader.discover() / BaseRegister.discover() enumerate a
    namespace's available modules (via pkgutil) instead of requiring
    callers to hand-maintain a list of names to register — combine with
    register_all() for "register everything found here, best-effort".
  - Lazy lets a register() entry point defer an object's actual
    construction until it's queried, instead of paying that cost (and
    risking failure) merely because the plugin was registered — see its
    class docstring for why that distinction matters in practice.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable, Iterable
from types import ModuleType
from typing import Any, NamedTuple


def _resolve_attr(
    module: ModuleType, attr_name: str, missing_error: type[PluginError]
) -> Any:
    """
    Return getattr(module, attr_name), or raise `missing_error` (chained off
    the original AttributeError) if it isn't found. Shared by ClassLoader and
    BaseRegister, which both need "resolve a named attribute off a loaded
    module or raise a domain-specific error" and differ only in which error.
    """
    try:
        return getattr(module, attr_name)
    except AttributeError as e:
        raise missing_error(
            f"Module {module.__name__!r} has no attribute {attr_name!r}"
        ) from e


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PluginError(Exception):
    """Base class for all plugin-system errors."""


class PluginNotFoundError(PluginError):
    """Raised when no module of the given name exists in the configured namespace."""


class PluginImportError(PluginError):
    """Raised when a module exists but raised an exception while being imported."""


class EntryClassMissingError(PluginError):
    """Raised when the configured entry_class attribute is not found on a module."""


class EntryClassInvalidError(PluginError):
    """Raised when the entry_class attribute exists but is not a class."""


class EntryClassConstructionError(PluginError):
    """Raised when the entry class was resolved but raised while being constructed."""


class EntryPointMissingError(PluginError):
    """Raised when the configured entry_point attribute is not found on a module."""


class EntryPointError(PluginError):
    """Raised when a module's entry point function raises when called."""


class AlreadyRegisteredError(PluginError):
    """Raised when register() is called again for a name that's already registered."""


class NotRegisteredError(PluginError):
    """Raised when get() is called for a name that has not been registered."""


class ObjectNotFoundError(PluginError):
    """Raised when a specific (plugin name, object name) pair can't be found."""


class ProtocolConformanceError(PluginError):
    """
    Raised when a single, specifically-requested object fails the isinstance()
    sanity check against the Protocol it was declared under. Note this is
    NOT raised by get_by_protocol() (broad queries skip+warn instead, since
    one bad entry shouldn't fail results for every other well-behaved plugin)
    — only by pinpoint single-object lookups, where there's no fallback to
    silently omit the entry from.
    """


class LazyResolutionError(PluginError):
    """
    Raised when a single, specifically-requested Lazy-wrapped object's
    factory raises while being resolved. Same broad-vs-pinpoint split as
    ProtocolConformanceError: get_by_protocol() skips+records a failed
    Lazy and keeps going (see get_resolution_failures()); only pinpoint
    lookups via get_object() raise.
    """


# ---------------------------------------------------------------------------
# ModuleLoader
# ---------------------------------------------------------------------------


class ModuleLoader:
    """Loads modules by short name from within a fixed namespace package."""

    def __init__(self, ns: str) -> None:
        """
        Args:
            ns: Dotted namespace package to load modules from, e.g. 'foo.plugins'.
                Not validated/imported here — validation is lazy, deferred to load().
        """
        self.ns = ns

    def load(self, name: str) -> ModuleType:
        """
        Import and return the module `{ns}.{name}`.

        Args:
            name: Short module name, relative to `self.ns`.

        Returns:
            The imported module object.

        Raises:
            PluginNotFoundError: No such module exists in the namespace.
            PluginImportError: The module exists but raised while importing
                (including a ModuleNotFoundError caused by one of *its own*
                missing dependencies, as opposed to the module itself missing).
        """
        full_name = f"{self.ns}.{name}"
        try:
            return importlib.import_module(full_name)
        except ModuleNotFoundError as e:
            if e.name == full_name:
                raise PluginNotFoundError(
                    f"No plugin named {name!r} in namespace {self.ns!r}"
                ) from e
            raise PluginImportError(
                f"Module {full_name!r} failed to import due to missing "
                f"dependency {e.name!r}"
            ) from e
        except Exception as e:
            raise PluginImportError(
                f"Module {full_name!r} raised while importing: {e}"
            ) from e

    def discover(self) -> list[str]:
        """
        Enumerate the short names of every module directly under this
        namespace package (one level, not recursive) — the same names
        load() accepts. Only the namespace package itself is imported to
        read its __path__; none of the discovered modules are imported,
        so a broken module doesn't prevent it from being *listed* (only
        from later loading successfully).

        Returns:
            Sorted list of short module names.

        Raises:
            PluginNotFoundError: The namespace package itself doesn't exist.
            PluginImportError: The namespace package exists but raised
                while importing.
        """
        try:
            namespace_module = importlib.import_module(self.ns)
        except ModuleNotFoundError as e:
            if e.name == self.ns:
                raise PluginNotFoundError(
                    f"Namespace {self.ns!r} does not exist"
                ) from e
            raise PluginImportError(
                f"Namespace {self.ns!r} failed to import due to missing "
                f"dependency {e.name!r}"
            ) from e
        except Exception as e:
            raise PluginImportError(
                f"Namespace {self.ns!r} raised while importing: {e}"
            ) from e

        return sorted(
            module_info.name
            for module_info in pkgutil.iter_modules(namespace_module.__path__)
        )


# ---------------------------------------------------------------------------
# ClassLoader
# ---------------------------------------------------------------------------


class ClassLoader:
    """Resolves and instantiates a named entry class from modules in a namespace."""

    def __init__(self, ns: str, entry_class: str) -> None:
        """
        Args:
            ns: Dotted namespace package, passed through to an internal ModuleLoader.
            entry_class: Attribute name of the class to resolve on each loaded module,
                e.g. 'PluginEntry'.
        """
        self.ns = ns
        self.entry_class = entry_class
        self._module_loader = ModuleLoader(ns)

    def get_class(self, name: str) -> type:
        """
        Resolve and return the entry class (not an instance) for module `name`.

        Args:
            name: Short module name, relative to `self.ns`.

        Returns:
            The class object `{ns}.{name}.{entry_class}`.

        Raises:
            PluginNotFoundError: No such module exists in the namespace.
            PluginImportError: The module exists but raised while importing.
            EntryClassMissingError: The module has no attribute named `entry_class`.
            EntryClassInvalidError: The attribute exists but is not a class.
        """
        module = self._module_loader.load(name)
        attr = _resolve_attr(module, self.entry_class, EntryClassMissingError)
        if not isinstance(attr, type):
            raise EntryClassInvalidError(
                f"{module.__name__}.{self.entry_class} is not a class "
                f"(got {type(attr).__name__})"
            )
        return attr

    def instantiate(self, name: str, *args: Any, **kwargs: Any) -> Any:
        """
        Resolve the entry class for module `name` and construct an instance of it.

        Args:
            name: Short module name, relative to `self.ns`.
            *args, **kwargs: Forwarded to the entry class's constructor.

        Returns:
            A new instance of `{ns}.{name}.{entry_class}`.

        Raises:
            PluginNotFoundError: No such module exists in the namespace.
            PluginImportError: The module exists but raised while importing.
            EntryClassMissingError: The module has no attribute named `entry_class`.
            EntryClassInvalidError: The attribute exists but is not a class.
            EntryClassConstructionError: The class was resolved but its __init__
                raised when called with the given args/kwargs.
        """
        cls = self.get_class(name)
        try:
            return cls(*args, **kwargs)
        except Exception as e:
            raise EntryClassConstructionError(
                f"Failed to construct {cls.__module__}.{cls.__qualname__}: {e}"
            ) from e


# ---------------------------------------------------------------------------
# BaseRegister
# ---------------------------------------------------------------------------


class BaseRegister:
    """
    Calls a module-level entry point function and stores its return value.

    No shape validation is done on what the entry point returns — it's stored
    as-is, keyed by module name. Use this directly (or subclass it) when you
    need unconstrained storage. Most applications want `Register` instead,
    which adds Protocol-aware querying on top of this.
    """

    def __init__(self, ns: str, entry_point: str) -> None:
        """
        Args:
            ns: Dotted namespace package, passed through to an internal ModuleLoader.
            entry_point: Attribute name of the callable to invoke on each module,
                e.g. '__foo_entry_point__'. Called with no arguments; its return
                value is stored as-is under the module's short name.
        """
        self.ns = ns
        self.entry_point = entry_point
        self._module_loader = ModuleLoader(ns)
        self._registry: dict[str, Any] = {}

    def register(self, name: str) -> None:
        """
        Load module `name`, call its entry point, and store the result.

        Order of operations (all must succeed before anything is stored):
            1. Check `name` isn't already registered.
            2. Load the module (via internal ModuleLoader).
            3. Resolve the entry_point attribute on it.
            4. Call the entry point.
            5. Store the return value under `name`.

        Args:
            name: Short module name, relative to `self.ns`.

        Raises:
            AlreadyRegisteredError: `name` is already registered.
            PluginNotFoundError: No such module exists in the namespace.
            PluginImportError: The module exists but raised while importing.
            EntryPointMissingError: The module has no attribute named `entry_point`.
            EntryPointError: The entry point was found but raised when called.
        """
        if name in self._registry:
            raise AlreadyRegisteredError(f"{name!r} is already registered")

        module = self._module_loader.load(name)
        entry_point_fn = _resolve_attr(module, self.entry_point, EntryPointMissingError)

        try:
            result = entry_point_fn()
        except Exception as e:
            raise EntryPointError(
                f"Entry point {module.__name__}.{self.entry_point} raised: {e}"
            ) from e

        self._registry[name] = result

    def discover(self) -> list[str]:
        """Enumerate module names available in this namespace — delegates
        to the internal ModuleLoader. See ModuleLoader.discover()."""
        return self._module_loader.discover()

    def register_all(
        self,
        names: Iterable[str],
        *,
        on_error: Callable[[str, PluginError], None] | None = None,
    ) -> list[str]:
        """
        Best-effort register() over multiple names: a name whose load or
        entry point fails is skipped rather than aborting the rest —
        pair with discover() for "register everything found here":
        `register.register_all(register.discover())`.

        Args:
            names: Short module names to attempt, in order.
            on_error: Optional callback invoked with (name, error) for
                each name that failed — e.g. for logging. Not called for
                AlreadyRegisteredError, which always propagates instead:
                it signals a caller bug (registering the same name
                twice), not a plugin-side failure to skip past.

        Returns:
            The names that registered successfully, in order.

        Raises:
            AlreadyRegisteredError: Any of `names` is already registered.
        """
        succeeded: list[str] = []
        for name in names:
            try:
                self.register(name)
            except AlreadyRegisteredError:
                raise
            except PluginError as e:
                if on_error is not None:
                    on_error(name, e)
                continue
            succeeded.append(name)
        return succeeded

    def get(self, name: str) -> Any:
        """
        Return the previously stored object(s) for module `name`.

        Args:
            name: Short module name that was previously passed to register().

        Returns:
            Whatever `name`'s entry point returned, unmodified.

        Raises:
            NotRegisteredError: `name` has not been registered.
        """
        try:
            return self._registry[name]
        except KeyError as e:
            raise NotRegisteredError(f"{name!r} has not been registered") from e


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------


class RegisteredObject(NamedTuple):
    """One object registered by a plugin: its per-plugin name, the Protocol it
    was declared as implementing, and the object itself."""

    name: str
    protocol: type
    obj: Any


class Lazy:
    """
    Wrap a zero-argument factory in a register() entry point's returned
    triple to defer the object's construction until it's actually
    queried (get_by_protocol/get_object), instead of at register() time.

    Motivation: register() may be called for every known plugin module
    regardless of whether an application ends up needing that particular
    one this run (e.g. a discovery step that registers everything found
    via discover()). If constructing the real object is costly or can
    fail — spawning a subprocess to check a binary's presence, opening a
    network connection, validating an API key — that cost/risk
    shouldn't be paid just because the plugin was *listed*. Wrapping it
    in Lazy defers it to the point where something actually asked for
    this specific object.

    The factory is called at most once; the result (or the exception,
    implicitly, since it isn't caught here) is cached, so repeated
    queries don't reconstruct it and identity stays stable.
    """

    __slots__ = ("_cached", "_factory", "_resolved")

    def __init__(self, factory: Callable[[], Any]) -> None:
        self._factory = factory
        self._cached: Any = None
        self._resolved = False

    def resolve(self) -> Any:
        if not self._resolved:
            self._cached = self._factory()
            self._resolved = True
        return self._cached


class Register(BaseRegister):
    """
    Protocol-aware plugin registry — the default most applications want.

    Entry points registered under this class must return
    `list[tuple[name, Protocol, object]]` (or an iterable of `RegisteredObject`)
    — one triple per object the plugin provides, explicitly declaring which
    application-defined Protocol each object implements. `name` disambiguates
    multiple objects from the same plugin implementing the same Protocol, and
    is only required to be unique within that one plugin's own returned list.
    `object` may itself be a `Lazy`-wrapped factory instead of a live
    instance — see Lazy's class docstring for when that's worth doing.

    Every Protocol used with this class must be `@runtime_checkable`
    (typing.Protocol), since queries use isinstance()/issubclass() against it.

    Falls back to BaseRegister's behavior for register()/get() — those are
    inherited unchanged. This class only adds Protocol-based query methods.
    """

    def __init__(self, ns: str, entry_point: str) -> None:
        super().__init__(ns=ns, entry_point=entry_point)
        self._conformance_warnings: list[RegisteredObject] = []
        self._resolution_failures: list[tuple[RegisteredObject, Exception]] = []

    def _entries(self, name: str):
        """Yield a RegisteredObject for every triple stored under plugin
        `name`, resolving any Lazy-wrapped object first. A triple whose
        Lazy factory raises is skipped and recorded in
        self._resolution_failures instead of propagating — same
        broad-query "one bad entry doesn't fail the rest" philosophy as
        _conformance_warnings. Pinpoint lookups don't go through here —
        see _find_entry(), which raises instead of skipping."""
        for triple in self.get(name):
            entry = RegisteredObject(*triple)
            if isinstance(entry.obj, Lazy):
                try:
                    resolved = entry.obj.resolve()
                except Exception as e:  # noqa: BLE001 — a plugin's Lazy factory
                    # can raise anything; broad and deliberate, same as
                    # BaseRegister.register()'s own entry-point catch —
                    # one bad plugin must not block every other one from
                    # being enumerated (see _find_entry() for the pinpoint
                    # counterpart, which re-raises instead).
                    self._resolution_failures.append((entry, e))
                    continue
                entry = entry._replace(obj=resolved)
            yield entry

    def _iter_all(self):
        """Yield (plugin_name, RegisteredObject) for every registered triple."""
        for plugin_name in self._registry:
            for entry in self._entries(plugin_name):
                yield plugin_name, entry

    def _find_entry(self, name: str, object_name: str) -> RegisteredObject:
        """Return the RegisteredObject named `object_name` within plugin
        `name`, resolving it if Lazy. Unlike the broad get_by_protocol()
        path (_entries()/_iter_all()), a resolution failure here raises
        LazyResolutionError rather than being skipped — there's no
        broader result set to silently omit a pinpoint lookup from."""
        for triple in self.get(name):
            entry = RegisteredObject(*triple)
            if entry.name != object_name:
                continue
            if isinstance(entry.obj, Lazy):
                try:
                    resolved = entry.obj.resolve()
                except Exception as e:
                    raise LazyResolutionError(
                        f"{name!r}.{object_name!r} failed to resolve: {e}"
                    ) from e
                return entry._replace(obj=resolved)
            return entry
        raise ObjectNotFoundError(
            f"No object named {object_name!r} registered under plugin {name!r}"
        )

    def get_by_protocol(self, protocol: type) -> list[tuple[str, str, Any]]:
        """
        Return every registered object declared as implementing `protocol`,
        across all registered plugins.

        Matching is hierarchy-aware: an object declared under a Protocol that
        is a subclass of `protocol` matches too (querying broad finds narrow;
        querying narrow does not find broad).

        Each match is also sanity-checked with isinstance(obj, protocol).
        Objects that fail this check are skipped from the result and appended
        to self._conformance_warnings rather than raising — one badly-behaved
        plugin doesn't fail the query for every other plugin.

        Args:
            protocol: The (runtime_checkable) Protocol to query for.

        Returns:
            List of (plugin_name, object_name, obj) tuples for every matching,
            conformance-verified object.
        """
        results: list[tuple[str, str, Any]] = []
        for plugin_name, entry in self._iter_all():
            if not issubclass(entry.protocol, protocol):
                continue
            if not isinstance(entry.obj, protocol):
                self._conformance_warnings.append(entry)
                continue
            results.append((plugin_name, entry.name, entry.obj))
        return results

    def get_object(
        self, name: str, object_name: str, protocol: type | None = None
    ) -> Any:
        """
        Return a single object registered by plugin `name` under the given
        per-plugin `object_name`.

        Args:
            name: Short plugin/module name, as passed to register().
            object_name: The per-plugin name the object was declared with.
            protocol: If given, additionally verify (hierarchy-aware) that the
                object's declared Protocol matches, and sanity-check it with
                isinstance(). Unlike get_by_protocol(), a conformance failure
                here raises rather than being skipped — there's no broader
                result set to fall back to for a single pinpoint lookup.

        Returns:
            The matching object.

        Raises:
            NotRegisteredError: `name` has not been registered at all.
            ObjectNotFoundError: `name` is registered, but no object with
                `object_name` exists in its returned list.
            ProtocolConformanceError: `protocol` was given, the object was
                found, but it fails the hierarchy/isinstance check against it.
        """
        entry = self._find_entry(name, object_name)  # raises NotRegisteredError /
        # ObjectNotFoundError as needed
        if protocol is None:
            return entry.obj
        if not issubclass(entry.protocol, protocol) or not isinstance(
            entry.obj, protocol
        ):
            raise ProtocolConformanceError(
                f"{name!r}.{object_name!r} does not conform to {protocol!r} "
                f"(declared as {entry.protocol!r})"
            )
        return entry.obj

    def get_conformance_warnings(self) -> list[RegisteredObject]:
        """
        Return a copy of the objects that have failed an isinstance() sanity
        check during get_by_protocol() calls so far (declared Protocol vs.
        actual structural conformance mismatch).
        """
        return list(self._conformance_warnings)

    def get_resolution_failures(self) -> list[tuple[RegisteredObject, Exception]]:
        """
        Return a copy of the (entry, exception) pairs where a Lazy-wrapped
        object's factory raised during a get_by_protocol() call so far.
        `entry.obj` on these is still the unresolved Lazy, not a real
        instance — the factory never completed.
        """
        return list(self._resolution_failures)
