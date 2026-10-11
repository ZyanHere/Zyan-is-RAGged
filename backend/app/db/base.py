"""The declarative base, and the constraint naming convention.

Nothing here is a model. This file exists almost entirely for the naming
convention, which has to be correct *before* the first migration is generated
and is expensive to retrofit afterwards.

── Why the naming convention matters ────────────────────────────────────────

Left to itself, Postgres invents names for constraints and indexes, and
SQLAlchemy does not know what it chose. That is harmless until Alembic tries to
write a `downgrade()`: dropping a constraint requires naming it, and Alembic
emits a guess. The guess is usually wrong, so the downgrade fails — and a
migration you cannot reverse is one you cannot safely deploy.

Fixing this later means a migration whose only job is renaming every constraint
in the database. Doing it now costs one dictionary.

The `%(constraint_name)s` token in the `ck` pattern is why every
`CheckConstraint` in `models.py` is given an explicit `name=`. Without one,
SQLAlchemy raises at table-definition time rather than producing a badly named
constraint — which is the right failure, loudly and early.
"""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base for every model in the backend.

    SQLAlchemy 2.0 style: a class inheriting `DeclarativeBase`, with columns
    declared as `Mapped[...]` and `mapped_column(...)`. The 1.x
    `declarative_base()` factory and bare `Column()` still work and are what
    most tutorials show — they give you no static typing, so a typo in an
    attribute name is a runtime `AttributeError` instead of a red squiggle.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
