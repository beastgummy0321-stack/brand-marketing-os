"""Platform-neutral, bounded read capabilities. No write method exists."""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class SourcePage:
    items: list[dict]
    cursor: dict | None = None
    errors: list[str] = field(default_factory=list)


class ExternalReader(Protocol):
    def accounts(self, conn, org_id, brand_id) -> list[dict]: ...
    def list_existing(self, conn, org_id, brand_id, account, **kwargs) -> SourcePage: ...
    def read_structure(self, conn, org_id, brand_id, account, **kwargs) -> SourcePage: ...
    def read_creatives(self, conn, org_id, brand_id, account, **kwargs) -> SourcePage: ...
    def read_observations(self, conn, org_id, brand_id, account, **kwargs) -> SourcePage: ...


class SourceReadError(ValueError):
    def __init__(self, message, code="source_error"):
        super().__init__(message)
        self.code = code
