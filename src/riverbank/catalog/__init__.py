from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

RIVERBANK_SCHEMA = "_riverbank"

metadata = MetaData(schema=RIVERBANK_SCHEMA)


class Base(DeclarativeBase):
    metadata = metadata
