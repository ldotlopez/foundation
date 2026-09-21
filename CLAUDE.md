# Agent Instructions & Project Guidelines

## Core Principles & Agentic Behavior

- **Refactor Before Implementing:** If a request violates core principles (SRP, KISS, DRY), rewrite the approach before coding, then briefly state what you changed and why.
- **Search Boundaries First:** Search local directories before traversing the tree. Edit existing files over creating new ones.
- **No Half-Baked Code:** Never leave `TODO` comments, placeholder logic, or mock returns in completed code.
- **Explicit Dependencies:** When adding an approved package, run `uv add <package>` (updating `pyproject.toml`) in the same step.
- **Communication Style:** Keep responses concise, direct, and non-verbose. Avoid filler, fluff, or excessive conversational preamble without becoming overly terse or abrupt, unless explicitly requested by the user.

---

## File System Traversal & Search Rules

1. **Strictly Scoped Searches:**
   - NEVER execute broad or recursive workspace searches (e.g., raw `grep -r`, `find .`, `ls -R`, or `**/*`) without specifying target paths and extensions.
   - Restrict searches to explicit subdirectories (e.g., `src/`, `tests/`) and specific extensions (e.g., `*.py`).

2. **Justified Broad Search Exception:**
   - If an unbounded/repo-wide search is strictly necessary (e.g., tracking cross-module refactors, global type mismatches, or missing exports):
     - **STOP before running the command.**
     - Ask the user for permission, explaining **why** it is justified and **what target pattern** you plan to use.
     - **Wait for explicit confirmation** before proceeding.

3. **Fallback & Escape Hatch:**
   - If targeted searches yield no results within 2 attempts, do NOT expand to full repo scanning. Stop and ask the user for the file path or module location.

---

## Tech Stack & Runtime

- **Python Target:** Python 3.13+
- **Package Manager:** `uv`
- **Pathing:** Exclusively use `pathlib.Path` (never `os.path` or string path operations).
- **Tooling:** Format and lint exclusively using `uv run ruff check --fix .` and `uv run ruff format .`.

---

## Object-Oriented Design & Decoupling Conventions

- **Pragmatic OOP:** Use Object-Oriented Programming (OOP) patterns where state and behavior belong together (e.g., domain entities, stateful processors, DB adapters). Avoid forcing pure functions or stateless helpers into fake "Utility" classes.
- **Structural Decoupling via `Protocol`:** Use Python's `typing.Protocol` for interface definition and loose coupling (duck typing with static verification).
  - Define consumer-side protocols: Components should define the protocol for the dependencies they consume, rather than inheriting from concrete base classes.
  - Avoid unnecessary `ABC` inheritance when a `Protocol` provides required decoupling without concrete base class coupling.
- **Composition Over Inheritance:** Prefer composing classes using protocol-typed attributes rather than deep class inheritance hierarchies.

---

## Data Transfer Objects (DTOs) vs Boundary Models

- **DTO Applicability:** DTOs (`dataclasses`) are specifically required to isolate the **database/persistence layer**. If the application has no DB or ORM layer, do NOT create artificial DTO abstractions—pass standard domain models or native data types directly.
- **Standard DTOs (`dataclasses`):** When a DB layer exists, internal Data Transfer Objects MUST be built using standard library `@dataclass(slots=True)` unless explicitly instructed otherwise.
- **Boundary Validation (`pydantic`):** Reserve `pydantic.BaseModel` strictly for complex or nested untrusted input boundaries (e.g., HTTP request bodies, external API responses, environment variables, or complex config files).
  - **CLI Exception:** Do NOT introduce `pydantic` solely to validate CLI arguments if standard Python data types (`int`, `float`, `str`, `Enum`, `Path`) handled by standard library `argparse` are sufficient.

---

## Python 3.13+ Type Annotation Rules

- **Mandatory Annotations:** Type-annotate **all** function signatures (arguments, return types) and class attributes.
- **Native Collections:** Use standard built-in generics directly (`list[str]`, `dict[str, Any]`, `set[Path]`, `tuple[int, ...]`). Do NOT import `List`, `Dict`, `Set`, or `Tuple` from `typing`.
- **Modern Unions & Optionals:** Use `A | B` for unions and `T | None` for optional values. Never import or use `Union` or `Optional`.
- **PEP 695 Type Aliases:** Use the `type` statement for type aliases (e.g., `type UserId = int`) instead of `TypeAlias` or assignment.
- **Explicit Returns:** Use `-> None` explicitly for functions/methods that return nothing.
- **Strict Typing Imports:** Only import typing constructs when built-ins are insufficient (`Protocol`, `Self`, `Override`, `TypedDict`, `Literal`, `Callable`).

---

## Dependency Policy

Standard library first. Introduce external packages only when they offer clear utility.

| Category / Requirement | Approved Package | Condition / Policy |
| :--- | :--- | :--- |
| **CLI Framework** | `argparse` *(stdlib)* / `click` | Use stdlib `argparse` for single-purpose/single-command scripts. Introduce `click` (or `rich-click`) ONLY if the application uses subcommands. |
| **Data Parsing & Boundary Validation** | `pydantic` | Use ONLY for complex boundary validation (API JSON, config files). Skip if `argparse` native typing is sufficient. |
| **HTTP Client** | `requests` | Use when standard library `urllib` is insufficient for complex API calls. |
| **Terminal Output & Progress** | `rich` | For enhanced UI, progress bars, or rich tables. |
| **Database ORM** | `sqlalchemy` | Used when persistent relational DB storage is required. |
| **Platform Integration & User Dirs** | `platformdirs` | For locating user/system data directories cleanly across OSes. |

*Do NOT introduce unlisted third-party packages without explicit user approval.*

---

## Code Style & Architecture Conventions

- **Focus (SRP & Clarity):** One job per function or class. Prefer direct readability over clever trickery; a reader should understand a method without tracing callers.
- **Naming:** Use domain-descriptive names. Approved abbreviations: `url`, `id`, `cfg`, `path`. Explicitly banned: `x`, `tmp`, `data`, `info`.
- **Exception Handling:** Raise specific exceptions. Banned pattern: `except Exception: pass`.
- **Pragmatism (KISS / YAGNI):** Solve the immediate problem. Avoid speculative abstractions.

---

## Database & ORM Conventions

- **DTO Boundary Isolation:** SQLAlchemy ORM models MUST NOT leak outside the database / data access layer.
  - Convert data passing into or out of the DB layer using `@dataclass` DTOs.
  - Every SQLAlchemy model must implement three explicit methods:
    - `from_dto(cls, dto: DTOType) -> Self`: Class method to instantiate a new DB model from a DTO.
    - `to_dto(self) -> DTOType`: Instance method to export model state to its corresponding `@dataclass` DTO.
    - `update(self, dto: DTOType) -> None`: Instance method to update all fields on the DB object from the DTO except the primary key/ID. Use explicit field assignment (`self.field = dto.field`) rather than reflective loops or `setattr` iterations.
- **Database-Native Integrity:** Prefer database-level constraints and triggers over ORM-level or Python-level validation hooks.
  - Define `CheckConstraint`, `UniqueConstraint`, and foreign key cascade rules directly in SQLAlchemy model table definitions so they execute natively in SQL.

### DTO, Protocol & ORM Implementation Reference

```python
from dataclasses import dataclass
from typing import Protocol, Self
from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


# Internal DTO based on dataclass (used specifically for DB isolation)
@dataclass(slots=True)
class UserDTO:
    id: int | None = None
    email: str | None = None
    username: str | None = None


# Decoupling Protocol
class UserRepository(Protocol):
    def get_by_id(self, user_id: int) -> UserDTO | None: ...
    def save(self, dto: UserDTO) -> UserDTO: ...


# ORM Implementation
class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_user_email"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str] = mapped_column(String(100), nullable=False)

    @classmethod
    def from_dto(cls, dto: UserDTO) -> Self:
        """Create a new DB instance from a DTO."""
        if dto.email is None or dto.username is None:
            raise ValueError("Email and username are required to instantiate a User")
        return cls(email=dto.email, username=dto.username)

    def to_dto(self) -> UserDTO:
        """Export model state to a Dataclass DTO."""
        return UserDTO(id=self.id, email=self.email, username=self.username)

    def update(self, dto: UserDTO) -> None:
        """Update all fields on the DB model from the DTO except the ID.

        Explicitly set fields directly rather than using dynamic field iteration.
        """
        if dto.email is not None:
            self.email = dto.email
        if dto.username is not None:
            self.username = dto.username
```

## Banned Practices

- Do NOT add unrequested logging, metrics, telemetry, or retry mechanisms.
- Do NOT generate boilerplate project files (`__init__.py`, `setup.cfg`, `py.typed`) unless explicitly requested.
- Do NOT add new abstraction layers without immediate, concrete use cases.
