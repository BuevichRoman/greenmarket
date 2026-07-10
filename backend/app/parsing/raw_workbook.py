from dataclasses import dataclass


@dataclass(frozen=True)
class RawSheet:
    name: str
    index: int
    rows: list[list[object]]


@dataclass(frozen=True)
class RawWorkbook:
    source: str
    sheets: list[RawSheet]
