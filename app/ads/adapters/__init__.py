"""app/ads/adapters/__init__.py — F03-I09: the publish interface, one registry, more than
one implementation (§0 the "action" link). Every adapter exposes exactly two functions:
    describe(campaign: dict) -> dict          # what the user must do / what will happen
    publish(conn, org_id, brand_id, campaign_id, *, actor) -> dict
F31-I08: there is no `bind` verb. The ads-center name-match bind had no screen calling it;
launch readback (F30-I12, `handoff_check`) binds each planned node to the platform object the
user proved. `get_adapter(name)` returns the adapter object (a plain module works — duck typing,
no ABC for two functions) or `None` when the name is unknown. `auto_meta` is a reserved third
entry: `describe` reports 「自動發布未接上」 (never phrased as a refusal — it is reserved, not
broken); `publish` raises `ValueError("auto_meta_not_connected")`, which `routes.py` turns into
a 400, never a 500. Private to app/ads (container contract §1): only `routes.py` imports this.
"""

from app.ads.adapters import manual, simulated

AUTO_META_NOT_CONNECTED_MESSAGE = "自動發布未接上"

# 給前端列選單用（決策 1：一般路徑「發布 Campaign」顯示「自動發布未接上」；進階選單才是
# 「手動發布」）——`simulated`（F03-I10：演練／驗收用）只加這一行，不改這個檔案的其餘部分。
ADAPTERS = [
    {"key": "manual", "label": "手動發布"},
    {"key": "auto_meta", "label": "自動發布（未接上）"},
    {"key": "simulated", "label": "模擬發布（演練用）"},
]


class _AutoMetaAdapter:
    """保留位置：目前唯一真的自動投放通路（Meta）沒有接上，呼叫一律被拒絕，但拒絕的方式
    是可讀的錯誤訊息，不是沒接住的例外（決策 1：不強迫使用者跑真廣告，這裡連想跑都跑不動，
    是「還沒接」，不是「壞了」）。"""

    def describe(self, campaign: dict) -> dict:  # noqa: ARG002 — 介面要求收 campaign
        return {"adapter": "auto_meta", "message": AUTO_META_NOT_CONNECTED_MESSAGE, "checklist": []}

    def publish(self, conn, org_id: str, brand_id: str, campaign_id: str, *, actor: str) -> dict:
        raise ValueError("auto_meta_not_connected")


_ADAPTERS = {
    "manual": manual,
    "auto_meta": _AutoMetaAdapter(),
    "simulated": simulated,
}


def get_adapter(name: str):
    """`manual`／`auto_meta`／`simulated` or `None`（未知名字）。"""
    return _ADAPTERS.get(name)


def platform_url(target: dict) -> str | None:
    """F22-I01: read-time-only deep link into a change item's own platform object, keyed by
    `target["platform"]` -- the one place a platform name maps to a read-side URL builder
    (`app/ads/change_control_data.py::get()` is the only caller). Lazy import, same seam
    `app/ads/channels.py::external_reader` already uses for the same module, to avoid a
    module-load-time cycle through `manual.py -> change_control_launch.py ->
    change_control_data.py`. Unknown platform, or an adapter with no such builder -> `None`,
    never a guessed link (`plan_json` never stores this -- no hash impact)."""
    if target.get("platform") == "meta":
        from app.ads.adapters import meta_read

        return meta_read.platform_url(target)
    return None


def copy_variants(platform: str | None, creative: dict) -> dict | None:
    """F27-I26: read-time-only dynamic-creative copy derivation, keyed by `platform` -- the one
    place a platform name maps to a copy-variant parser (`change_control_data.copy_fields`/
    `copy_editable` are the only callers, for any stored creative whose `fields.copy_variants`
    is missing, e.g. synced before F27-I02). Same lazy-import seam as `platform_url` above, to
    avoid the module-load-time cycle through `manual.py -> change_control_launch.py ->
    change_control_data.py`. Unknown platform, or a creative with nothing this platform's parser
    recognises -> `None`, never a guessed empty result -- the caller decides what "no answer"
    means (`copy_fields`: empty lists; `copy_editable`: still editable unless catalog-only)."""
    if platform == "meta":
        from app.ads.adapters import meta_read

        return meta_read.copy_variants(creative)
    return None


def is_auth_error(platform: str | None, code: str | None) -> bool:
    """F27-I09 Contract I / correction 2: whether a synced section's own STORED error code (never
    a raw provider number -- see the Meta adapter's own `is_auth_error`) means this platform
    connection's own read permission needs re-authorizing, not just a retry. Same lazy-import
    dispatch seam as `platform_url`/`copy_variants` above. Unknown platform, or a code this
    platform's adapter doesn't recognise -> `False`, never a guess."""
    if platform == "meta":
        from app.ads.adapters import meta_read

        return meta_read.is_auth_error(code)
    return False


UNKNOWN_DELIVERY = ("unknown", "平台狀態不明")


def _status_table(platform: str | None) -> dict:
    """The platform's own native status -> (delivery state, label) table. The simulated platform
    writes Meta's vocabulary (`simulated.py` registers its nodes as Meta would report them), so it
    reads Meta's table. Same lazy-import dispatch seam as `platform_url` above."""
    if platform in ("meta", "simulated"):
        from app.ads.adapters import meta_read

        return meta_read.STATUS_TABLE
    return {}


def delivery(platform: str | None, native_status: str | None) -> dict:
    """F49 Contract L: `{state, label}` of one platform object's stored native status --
    `running | not_running | off | unknown`. None, an unmapped status or an unknown platform ->
    `unknown` 平台狀態不明, never a guess. `app/ads/lifecycle.py` is the only caller."""
    state, label = _status_table(platform).get(native_status, UNKNOWN_DELIVERY) \
        if native_status is not None else UNKNOWN_DELIVERY
    return {"state": state, "label": label}


def _read_module(platform: str | None):
    """The platform's read adapter module (`creative_links`／`audience_ids`), or None for a
    platform without one. Same lazy-import dispatch seam as `platform_url` above."""
    if platform == "meta":
        from app.ads.adapters import meta_read

        return meta_read
    if platform == "simulated":
        from app.ads.adapters import simulated_read

        return simulated_read
    return None


def creative_links(entity: dict) -> list[str] | None:
    """F49 Contract B: every destination URL one read ad's creative sends people to, in the
    platform's own creative shape; `[]` when the creative was read and names none, None when no
    creative was read (or the platform has no reader). Readback (`handoff_check`) compares them
    with the plan's landing URL and names no platform field itself."""
    module = _read_module(entity.get("platform"))
    return module.creative_links(entity) if module is not None else None


def audience_ids(entity: dict) -> list[str] | None:
    """F49 Contract B: the platform audience ids one read ad set targets; `[]` when its targeting
    was read and holds none, None when no targeting was read (or the platform has no reader)."""
    module = _read_module(entity.get("platform"))
    return module.audience_ids(entity) if module is not None else None


def gone(platform: str | None, native_status: str | None) -> bool:
    """Whether this stored native status says the object no longer exists on the platform (a
    subset of `off`). Unknown platform or status -> `False`."""
    if platform in ("meta", "simulated"):
        from app.ads.adapters import meta_read

        return native_status in meta_read.GONE_STATUSES
    return False


def pixel_id_error(platform: str | None, pixel_id: str) -> str | None:
    """F47-I06 (Contract A ids): the pixel-id format belongs to the platform adapter. The
    sentence for a typed pixel id this platform could never have issued, else `None`. A platform
    without a rule accepts any non-empty text (`launch_settings.normalize` refuses an empty one).
    Same lazy-import dispatch seam as `platform_url` above."""
    if platform == "meta":
        from app.ads.adapters import meta_read

        return meta_read.pixel_id_error(pixel_id)
    return None


def objective_family(platform: str | None, objective: str | None) -> str:
    """F27-I09 Done #7: this platform's own raw objective string -> `campaign_objective` family
    (`"sales"|"engagement"|"traffic"|"other"`), for an IMPORTED campaign only -- a system-built
    campaign's Chinese objective label routes through `repository.objective_family()` instead,
    never through here. Same lazy-import dispatch seam as `platform_url`/`copy_variants` above.
    Unknown platform -> `"other"`, never a guess."""
    if platform == "meta":
        from app.ads.adapters import meta_read

        return meta_read.objective_family(objective)
    return "other"
