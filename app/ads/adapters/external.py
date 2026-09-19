"""Platform-neutral, bounded read capabilities. No write method exists."""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class SourcePage:
    items: list[dict]
    cursor: dict | None = None
    errors: list[str] = field(default_factory=list)
    coverage: dict | None = None


class ExternalReader(Protocol):
    def accounts(self, conn, org_id, brand_id) -> list[dict]: ...
    def sync_scopes(self, conn) -> list[dict]: ...
    def read_monthly(
        self, conn, org_id, brand_id, account, *, start, end, cursor=None, **kwargs
    ) -> SourcePage: ...
    def binding_kinds(self) -> tuple[str, ...]: ...
    def verify_native(
        self,
        conn,
        org_id,
        brand_id,
        account,
        *,
        native_kind,
        native_id,
        root_kind,
        root_id,
        original,
    ) -> dict: ...

    # verify_native: fresh entity + complete parents, account timezone, optional explicit
    # media_equivalence(asset_sha256,copy_hash,creative_hash,basis) and continuous intervals.
    # Two matching snapshots are never a continuous-history contract.

    def list_existing(self, conn, org_id, brand_id, account, **kwargs) -> SourcePage: ...
    def read_structure(self, conn, org_id, brand_id, account, **kwargs) -> SourcePage: ...
    def read_creatives(self, conn, org_id, brand_id, account, **kwargs) -> SourcePage: ...
    def read_observations(self, conn, org_id, brand_id, account, **kwargs) -> SourcePage: ...


class SourceReadError(ValueError):
    def __init__(self, message, code="source_error"):
        super().__init__(message)
        self.code = code
