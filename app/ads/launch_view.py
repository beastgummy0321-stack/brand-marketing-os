"""F30 Contract G: one view of a campaign's first launch and the batch operations the publish
page needs -- readback of every built item, unreport, per-field confirm. Local records and
read-only platform reads only: nothing here writes to a platform. Each readback is the existing
`handoff_check.check`; this module only finds the platform object to check by exact name under
its expected parent."""

from datetime import datetime

from app.ads import change_control_data as changes
from app.ads import change_control_launch as launch
from app.ads import channels, external_sync, handoff_check, handoff_data, manual_settings, targets
from app.ads import repository as ads_repo

_STATES = {
    "pending": "todo",
    "reported": "built",
    "confirmed": "verified",
    "deviated": "mismatch",
    "unknown": "unknown",
    "stale": "changed",
}
# Items a batch readback reads (again): the user said they are built and they are not verified.
_READABLE = {"reported", "unknown", "deviated"}
_KIND_ORDER = {"campaign": 0, "group": 1, "ad": 2}
_KIND_LABELS = {"campaign": "活動", "group": "廣告組", "ad": "廣告"}
# One vocabulary with the readback's `mismatches`/`unreadable` keys (`handoff_check`), so a
# mismatch attaches to its field row. The ad copy keys are the platform's (title = headline).
_LABELS = handoff_check._FIELD_LABELS
_COPY_FIELDS = (
    ("title", "headline"),
    ("body", "body"),
    ("description", "description"),
)
_SETTING_LABELS = {f["key"]: f["label"] for f in manual_settings.FIELDS}
# Bounded platform reads per readback call (pages of one listing).
_PAGE_LIMIT = 20
# F36-I07 (Contract V): the plan's group roles, a local copy of `strategy._ROLE_LABELS` -- this
# module never imports the strategy layer. An unknown role would print its key (there is none:
# the column is CHECK-constrained to these three).
_ROLE_LABELS = {"new": "新客", "retarget": "再行銷", "explore": "探索"}
# F38 (decision 3): a fixed exclusion sentence per plan role -- text only, no lookup, never a
# platform audience mapping.
_ROLE_EXCLUSIONS = {
    "new": "排除：已購買者",
    "explore": "排除：已購買者",
    "retarget": "只投：互動過或買過的人",
}
AUDIENCE_HINT_KEY = "audience_hint"
AUDIENCE_HINT_LABEL = "受眾提示"


def _plain(value):
    return value if value is None or isinstance(value, (str, int, float, bool)) else str(value)


def _number(value):
    return None if value is None else float(value)


# -- the audience hint (F36-I07, Contract V) ------------------------------------------------------


def audience_hints(conn, org, brand, detail):
    """group id -> 「<角色>・<受眾 label1>、<label2>・簡報受眾：<text>・<排除句>」 for every
    group of `detail` (`repository.campaign_detail`) that yields at least one part. Read-only
    help for the person building the ad set by hand: the plan's role, the distinct audience
    coordinates of the group's ads in the brand's own words (`coordinate_vocabulary`,
    dimension `audience`; a key without a vocabulary row prints itself), the brief's own
    audience text (`context_json.audience_hint`, skipped when empty) and a fixed per-role
    exclusion sentence (F38: `new`/`explore` -> 「排除：已購買者」, `retarget` ->
    「只投：互動過或買過的人」; no role, no sentence). Never a platform targeting mapping
    (F36 ruling E: no age/interest inference, no Meta field), never part of the frozen
    snapshot or `expected_json` -- computed at view time only, so readback (`handoff_check`)
    is untouched and an approved launch never goes stale over it."""
    labels = {
        row["key"]: row["label"]
        for row in ads_repo.coordinate_vocabulary(conn, org, brand)
        if row["dimension"] == "audience"
    }
    brief_hint = (detail.get("context_json") or {}).get("audience_hint")
    brief_hint = brief_hint.strip() if isinstance(brief_hint, str) else ""
    hints = {}
    for group in detail.get("groups") or []:
        role = group.get("role")
        keys = []
        for ad in group.get("ads") or []:
            key = ad.get("audience_key")
            if key and key not in keys:
                keys.append(key)
        parts = [
            _ROLE_LABELS.get(role, role) if role else None,
            "、".join(labels.get(key, key) for key in keys) if keys else None,
            f"簡報受眾：{brief_hint}" if brief_hint else None,
            _ROLE_EXCLUSIONS.get(role) if role else None,
        ]
        text = "・".join(part for part in parts if part)
        if text:
            hints[group["id"]] = text
    return hints


# -- the view -------------------------------------------------------------------------------------


def _nodes(snapshot):
    """(kind, planned id) -> (node, parent name), in checklist order."""
    found = {("campaign", snapshot["id"]): (snapshot, None)}
    for group in snapshot.get("groups") or []:
        found[("group", group["id"])] = (group, snapshot.get("name"))
        for ad in group.get("ads") or []:
            found[("ad", ad["id"])] = (ad, group.get("name"))
    return found


def _fields(kind, node, parent_name, snapshot, hints=None):
    if kind == "campaign":
        rows = [
            ("name", "名稱", node.get("name")),
            ("objective", _LABELS["objective"], node.get("objective")),
            ("start_date", _LABELS["start_date"], node.get("start_date")),
            ("end_date", _LABELS["end_date"], node.get("end_date")),
        ]
    elif kind == "group":
        values = next(
            (
                m.get("values") or {}
                for m in snapshot.get("manual_settings") or []
                if m.get("id") == node["id"]
            ),
            {},
        )
        rows = [
            ("name", "名稱", node.get("name")),
            ("budget_amount", _LABELS["budget_amount"], _number(node.get("daily_budget"))),
            (
                "start_date",
                _LABELS["start_date"],
                node.get("start_date") or snapshot.get("start_date"),
            ),
            ("end_date", _LABELS["end_date"], node.get("end_date") or snapshot.get("end_date")),
            # Contract V: after the date rows, only for a group that has a hint.
            *(
                [(AUDIENCE_HINT_KEY, AUDIENCE_HINT_LABEL, hints[node["id"]])]
                if hints and node["id"] in hints
                else []
            ),
            *(
                ("manual_settings." + key, _SETTING_LABELS.get(key, key), value)
                for key, value in values.items()
                if value
            ),
        ]
    else:
        material = node.get("material_assignment") or {}
        copy = material.get("copy_fields") or {}
        rows = [
            ("name", "名稱", node.get("name")),
            ("group", "放在", parent_name),
            ("material", "素材", launch._material_label(material or None)),
            *(
                ("copy." + key, handoff_check._COPY_LABELS[key], copy[source])
                for key, source in _COPY_FIELDS
                if copy.get(source)
            ),
        ]
    return [{"key": key, "label": label, "value": _plain(value)} for key, label, value in rows]


def _planned_items(snapshot, hints):
    """Before approval: the batch the approval would freeze, nothing done yet."""
    return [
        {
            "id": planned_id,
            "kind": kind,
            "name": node.get("name"),
            "parent_name": parent_name,
            "fields": _fields(kind, node, parent_name, snapshot, hints),
            "state": "todo",
            "mismatches": [],
            "unreadable": [],
            "reason": None,
        }
        for (kind, planned_id), (node, parent_name) in _nodes(snapshot).items()
    ]


def _batch_rows(conn, org, brand, campaign_id, set_id):
    """The launch set's own handoff items -- a new-ad handoff is another set, never counted."""
    return [
        dict(r)
        for r in conn.execute(
            "SELECT h.*,p.name AS parent_name FROM ads_handoff_item h "
            "LEFT JOIN ads_handoff_item p ON p.id=h.parent_item_id "
            "WHERE h.org_id=%s AND h.brand_id=%s AND h.campaign_id=%s AND h.change_set_id=%s "
            "ORDER BY h.created_at,h.id",
            (org, brand, campaign_id, set_id),
        ).fetchall()
    ]


def _reason(row, state):
    evidence = row["evidence_json"] or {}
    note = (evidence.get("readback") or {}).get("reason")
    if state == "built":
        return note
    if state == "unknown":
        return note or evidence.get("message")
    return None


def _item(row, state, snapshot, nodes, hints):
    evidence = row["evidence_json"] or {}
    node, parent_name = nodes.get((row["planned_kind"], row["planned_id"]), (None, None))
    fields = (
        _fields(row["planned_kind"], node, parent_name, snapshot, hints)
        if node is not None
        else [{"key": "name", "label": "名稱", "value": row["name"]}]
    )
    checked = state in {"mismatch", "unknown", "verified"}
    confirmed = evidence.get("confirmed") or {}
    return {
        "id": row["id"],
        "kind": row["planned_kind"],
        "name": row["name"],
        "parent_name": row["parent_name"],
        "fields": fields,
        "state": state,
        "mismatches": list(evidence.get("mismatches") or []) if checked else [],
        "unreadable": [
            {"key": u["key"], "label": u["label"], "confirmed": u["key"] in confirmed}
            for u in evidence.get("unreadable") or []
        ]
        if checked
        else [],
        "reason": _reason(row, state),
    }


def _stamp(value):
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return value


def _read_at(rows):
    stamps = []
    for row in rows:
        evidence = row["evidence_json"] or {}
        stamps.extend(
            _stamp(v)
            for v in (
                row["observed_at"],
                evidence.get("attempted_at"),
                (evidence.get("readback") or {}).get("at"),
            )
        )
    stamps = [s for s in stamps if s is not None]
    return max(stamps) if stamps else None


def _summary(snapshot, campaign, current, deferred):
    groups = snapshot.get("groups") or []
    budgets = [g.get("daily_budget") for g in groups]
    planned = [a for g in current.get("groups") or [] for a in g.get("ads") or []]
    # A handed-off ad whose material became invalid stays in the batch but is not ready.
    ready = sum(launch.ready_material(a.get("material_assignment")) for a in planned)
    return {
        "campaigns": 1,
        "groups": len(groups),
        "ads": sum(len(g.get("ads") or []) for g in groups),
        "daily_total": float(sum(float(b) for b in budgets))
        if groups and all(b is not None for b in budgets)
        else None,
        "start": _plain(snapshot.get("start_date")),
        "end": _plain(snapshot.get("end_date")),
        "cap": targets.own_cap(campaign),
        "slots_ready": ready,
        "slots_total": len(planned) + len(deferred),
    }


def view(conn, org, brand, campaign_id):
    """`GET …/campaigns/{c}/launch`: step, version, approval time, the batch summary, this
    batch's items with their state, the ads deferred for lack of material and the launch-settings
    readback. F41-I03: the list step also carries `month_budget` (`launch.month_fit`, the same
    numbers approve's month preflight uses) for the first-launch list page's 「本月預算放得下」
    card; approved steps carry `None`."""
    campaign = changes.campaign(conn, org, brand, campaign_id)
    deferred: list = []
    current = launch.snapshot(conn, org, brand, campaign_id, deferred=deferred)
    # Contract V: the hint is read from the plan as it is now (the snapshot carries only
    # platform-shaped keys), keyed by group id so a frozen group finds its own.
    hints = audience_hints(
        conn, org, brand, ads_repo.campaign_detail(conn, org, brand, campaign_id) or {}
    )
    change_set = launch.launch_set(conn, org, brand, campaign_id)
    if change_set is None:
        return {
            "step": "list",
            "version": None,
            "approved_at": None,
            "summary": _summary(current, campaign, current, deferred),
            "items": _planned_items(current, hints),
            "deferred_ads": deferred,
            "read_at": None,
            "settings_readback": None,
            "month_budget": launch.month_fit(conn, org, brand, campaign_id, current),
        }
    frozen = change_set["plan_json"]["launch_snapshot"]
    stale = launch.stale(conn, org, brand, campaign_id, current=current)
    changed = {d["item_id"] for d in (stale or {}).get("diff", []) if d.get("item_id")}
    rows = _batch_rows(conn, org, brand, campaign_id, change_set["id"])
    nodes = _nodes(frozen)
    order = {key: index for index, key in enumerate(nodes)}
    rows.sort(key=lambda r: order.get((r["planned_kind"], r["planned_id"]), len(order)))
    items = [
        _item(
            row,
            "changed" if row["id"] in changed else _STATES.get(row["status"], "unknown"),
            frozen,
            nodes,
            hints,
        )
        for row in rows
    ]
    read_at = _read_at(rows)
    return {
        "step": "stale" if stale else "verify" if read_at is not None else "platform",
        "version": int(change_set["plan_json"].get("version") or 1),
        "approved_at": change_set["approved_at"],
        "summary": _summary(frozen, campaign, current, deferred),
        "items": items,
        "deferred_ads": deferred,
        "read_at": read_at,
        "settings_readback": handoff_check.settings_readback(conn, org, brand, campaign_id),
        "month_budget": None,
    }


# -- batch operations -----------------------------------------------------------------------------


def _current_set(conn, org, brand, campaign_id):
    changes.campaign(conn, org, brand, campaign_id)
    change_set = launch.launch_set(conn, org, brand, campaign_id)
    if change_set is None:
        raise ValueError("還沒有核准的上架清單。")
    return change_set


def _batch_item(conn, org, brand, campaign_id, item_id):
    change_set = _current_set(conn, org, brand, campaign_id)
    item = handoff_data.get(conn, org, brand, campaign_id, item_id)
    if item["change_set_id"] != change_set["id"]:
        raise ValueError("這一項不在目前核准的上架清單裡。")
    return item


def _pages(fetch):
    items, cursor = [], None
    for _ in range(_PAGE_LIMIT):
        page = fetch(cursor)
        items.extend(page.items)
        cursor = page.cursor
        if not cursor:
            return items
    raise ValueError("平台上的物件太多，這次沒有讀完，請稍後再讀回一次。")


def _identity(entity):
    return {
        "platform": entity["platform"],
        "source_account": entity["source_account"],
        "native_kind": entity["native_kind"],
        "native_id": entity["native_id"],
        "user_verified": False,
    }


def _platform(conn, org, brand, campaign_id):
    keys = [
        r["channel_key"]
        for r in conn.execute(
            "SELECT DISTINCT channel_key FROM ads_delivery_group WHERE org_id=%s AND brand_id=%s "
            "AND campaign_id=%s",
            (org, brand, campaign_id),
        ).fetchall()
    ]
    if len(keys) != 1:
        raise ValueError("這個活動的投放組不在同一個平台，無法自動比對名稱。")
    return keys[0]


def _roots(conn, org, brand, campaign_id, name):
    """Platform campaigns named exactly `name` in every account bound to this brand."""
    platform = _platform(conn, org, brand, campaign_id)
    reader = channels.external_reader(platform)
    if reader is None:
        raise ValueError("這個平台還不能讀回。")
    found = []
    for account in reader.accounts(conn, org, brand):
        found.extend(
            entity
            for entity in _pages(
                lambda cursor, account=account: reader.list_existing(
                    conn, org, brand, account, cursor=cursor
                )
            )
            if entity.get("name") == name
        )
    return found


def _children(conn, org, brand, campaign_id, item, cache):
    """Platform objects named exactly like `item` directly under its read-back parent."""
    parent = handoff_data.get(conn, org, brand, campaign_id, item["parent_item_id"])
    if not parent["entity_id"]:
        raise ValueError("上一層還沒讀回，這一項先不比對。")
    root = (
        parent
        if item["planned_kind"] == "group"
        else handoff_data.get(conn, org, brand, campaign_id, parent["parent_item_id"])
    )
    if not root["entity_id"]:
        raise ValueError("活動還沒讀回，這一項先不比對。")
    reader, account = external_sync.account_reader(
        conn, org, brand, parent["platform"], parent["source_account"]
    )
    key = (parent["platform"], parent["source_account"], root["native_id"])
    if key not in cache:
        cache[key] = _pages(
            lambda cursor: reader.read_structure(
                conn, org, brand, account, native_id=root["native_id"], cursor=cursor
            )
        )
    # The creative level is the reader's own binding kind; no platform level is named here.
    binding = set(reader.binding_kinds())
    wanted_binding = item["planned_kind"] == "ad"
    return [
        entity
        for entity in cache[key]
        if entity.get("parent_native_id") == parent["native_id"]
        and (entity.get("native_kind") in binding) == wanted_binding
        and entity.get("name") == item["name"]
    ]


def _match(conn, org, brand, campaign_id, item, cache):
    if item["entity_id"]:
        return _identity(item)
    kind = item["planned_kind"]
    found = (
        _roots(conn, org, brand, campaign_id, item["name"])
        if kind == "campaign"
        else _children(conn, org, brand, campaign_id, item, cache)
    )
    label = _KIND_LABELS[kind]
    if not found:
        raise ValueError(f"平台上找不到名稱是「{item['name']}」的{label}；名稱要一字不差。")
    if len(found) > 1:
        raise ValueError(
            f"平台上有 {len(found)} 個名稱都是「{item['name']}」的{label}，"
            "請把平台上的名稱改成不重複再讀回。"
        )
    return _identity(found[0])


def readback(conn, org, brand, campaign_id, actor):
    """`POST …/launch/readback`: every built (reported, not verified) item of the batch, parents
    first, matched by exact name under its expected parent and checked through the existing
    readback. Not found or ambiguous leaves the item as it was, with the reason."""
    change_set = _current_set(conn, org, brand, campaign_id)
    if launch.is_stale(conn, org, brand, campaign_id):
        raise ValueError("核准後方案又改過，請先決定用哪一版，再讀回。")
    rows = _batch_rows(conn, org, brand, campaign_id, change_set["id"])
    rows.sort(key=lambda r: _KIND_ORDER[r["planned_kind"]])
    cache: dict = {}
    for row in rows:
        if row["reported_at"] is None or row["status"] not in _READABLE:
            continue
        item = handoff_data.get(conn, org, brand, campaign_id, row["id"])
        try:
            payload = _match(conn, org, brand, campaign_id, item, cache)
            handoff_check.check(conn, org, brand, campaign_id, item["id"], payload, actor)
        except ValueError as exc:
            conn.rollback()
            handoff_data.note_readback(conn, org, brand, campaign_id, item["id"], str(exc))
    return view(conn, org, brand, campaign_id)


def unreport(conn, org, brand, campaign_id, item_id):
    """`POST …/launch/items/{id}/unreport`: clear a report while the item is not verified."""
    _batch_item(conn, org, brand, campaign_id, item_id)
    handoff_data.unreport(conn, org, brand, campaign_id, item_id)
    return view(conn, org, brand, campaign_id)


def confirm(conn, org, brand, campaign_id, item_id, key, actor):
    """`POST …/launch/items/{id}/confirm {key}`: the user confirms by eye one field the read could
    not see; the item is verified once every readable field matches and every unreadable one is
    confirmed."""
    _batch_item(conn, org, brand, campaign_id, item_id)
    handoff_check.confirm_field(conn, org, brand, campaign_id, item_id, key, actor)
    return view(conn, org, brand, campaign_id)
