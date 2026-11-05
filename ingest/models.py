"""Dataclasses passed between the stages."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Warning:
    record: int | None
    field: str | None
    code: str


@dataclass
class RawRecord:
    number: int
    line: int
    cells: list[str]
    original: str


@dataclass
class Rejected:
    record: int
    codes: list[str]
    original: str


@dataclass
class ReadResult:
    header: list[str]
    delimiter: str
    records: list[RawRecord]
    rejected: list[Rejected]
    warnings: list[Warning]
    rows_received: int


@dataclass
class ColumnMap:
    column: str
    field: str | None
    source: str


@dataclass
class FieldResult:
    value: str
    codes: list[str] = field(default_factory=list)


@dataclass
class Duplicate:
    card_number: str
    record: int
    last_interaction_at: str
    kept_record: int
    reason: str


@dataclass
class Outcome:
    canonical: list[dict[str, str]]
    rejected: list[Rejected]
    duplicates: list[Duplicate]
    warnings: list[Warning]
