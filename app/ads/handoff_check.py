"""Fresh read-only native verification with scoped ownership and late-response protection."""

from urllib.parse import parse_qsl, urlsplit

from psycopg.errors import LockNotAvailable

from app.ads import (
    adapters,
    asset_binding,
    change_control_launch,
    external_sync,
    handoff_data,
    launch_settings,
    manual_settings,
)
from app.ads import asset_binding_repository as bindings
from app.ads import change_control_data as changes
from app.ads import external_repository as external
from app.ads import repository as campaigns
from app.ads.external_models import ExternalEntity
from app.core import db

# F49 Contract B: why a readback could not prove an item -- one sentence per reason code. Every
# refusal raised here carries its code (`Refused`), a source read its `SourceReadError.code`; the
# evidence stores `reason_code` and this sentence, and the launch view prints it.
READBACK_REASONS = {
    # Refusals raised by the readback itself.
    "not_approved": "此交接尚未核准。",
    "parent_unread": "上一層還沒讀回，這一項先不比對。",
    "root_unread": "活動還沒讀回，這一項先不比對。",
    "account_mismatch": "來源帳號必須與已讀回父層一致。",
    "identity_taken": "此交接已對應另一個平台物件，不能覆寫既有身分。",
    "original_as_new": "新測試必須使用獨立廣告，不能把原廣告當成新廣告。",
    "preexisting_ad": "此廣告在建立新測試前已存在，請選新增廣告的獨立身分。",
    "wrong_level": "請選擇可對應素材的廣告層級。",
    "parent_mismatch": "平台直接父層與交接計畫不符。",
    "root_required": "活動交接必須選擇來源根層級。",
    "owned_elsewhere": "此平台物件已屬於另一個品牌或活動，不可重新掛接。",
    "owned_by_plan": "此平台活動已有其他內部計畫歸屬，不可重新掛接。",
    "item_taken": "此平台物件已對應另一個交接項目。",
    "source_changed": "核對期間來源已更新，保留較新的資料，請再核對。",
    "plan_changed": "核准後計畫或素材已變更，請重新檢視交接。",
    # What a read compared and found different, or could not read (never a 「請到平台看」).
    "landing_url_mismatch": "廣告連到的網址跟核准的落地頁不一樣。",
    "landing_url_unread": "這次讀回沒讀到廣告連到的網址，請稍後再讀回一次。",
    "audience_mismatch": "廣告組的受眾裡沒有核准的平台受眾 ID。",
    "audience_unread": "這次讀回沒讀到廣告組的受眾設定，請稍後再讀回一次。",
    "chain_mismatch": "平台回讀的上下層跟選的物件對不起來，請重新選擇後再讀回。",
    "material_unverified": "素材對應沒能核對（素材版本或對應已改變），請重新讀回。",
    "identity_unselected": "尚未選定這則新廣告的平台身分，請在交接清單選擇後再讀回。",
    "identity_ambiguous": "這個素材安排有多個平台對應，請在交接清單確認唯一身分後再讀回。",
    # The batch readback's name match (`launch_view._match`).
    "not_found": "平台上找不到名稱是「{name}」的{kind}；名稱要一字不差。",
    "ambiguous": (
        "平台上有 {count} 個名稱都是「{name}」的{kind}，請把平台上的名稱改成不重複再讀回。"
    ),
    "platform_split": "這個活動的投放組不在同一個平台，無法自動比對名稱。",
    # A source read's own codes (`SourceReadError.code`).
    "disconnected": "廣告帳號已解除連線或不屬於這個品牌，請到資料連線重新連上。",
    "permission_denied": "這個廣告帳號沒有讀取權限，請到資料連線檢查授權。",
    "unsupported": "這個平台還不能讀回這種物件。",
    "page_limit": "平台上的物件太多，這次沒有讀完，請稍後再讀回一次。",
    "invalid_source_page": "平台回的資料不完整，請再讀回一次。",
    "source_error": "平台這次沒有回應，請稍後再讀回。",
    # Anything else: the read could not prove the item, nothing more is known.
    "unverifiable": "來源、物件歸屬或完整設定無法核對，未確認完成；請核對選擇後重試。",
}


def reason_text(code, **params) -> str:
    """The sentence for `code` (unknown codes read as `unverifiable`)."""
    return READBACK_REASONS.get(code, READBACK_REASONS["unverifiable"]).format(**params)


class Refused(ValueError):
    """A readback refusal carrying its reason code; the message is the code's sentence."""

    def __init__(self, code, **params):
        super().__init__(reason_text(code, **params))
        self.code = code


def refusal(exc: ValueError) -> tuple[str, str]:
    """`(reason_code, sentence)` of a caught refusal: the code it carries (`Refused`／
    `SourceReadError`), else `unverifiable`; the sentence always from `READBACK_REASONS` (a
    `Refused` message already is one, with its names filled in) -- a source's own message never
    reaches the user."""
    code = getattr(exc, "code", None) or "unverifiable"
    return code, str(exc) if isinstance(exc, Refused) else reason_text(code)


def _coded(code, call, *args, **kwargs):
    """Run `call`; a plain `ValueError` from it (another module's refusal without a code) becomes
    `Refused(code)`. A coded one passes through as raised."""
    try:
        return call(*args, **kwargs)
    except ValueError as exc:
        if getattr(exc, "code", None):
            raise
        raise Refused(code) from exc


def _launch_current(conn, org, brand, campaign, change_set):
    original = change_set["plan_json"].get("launch_snapshot")
    if original is None:
        return True
    current = change_control_launch.snapshot(conn, org, brand, campaign)
    # The same comparison `GET …/handoff` reports as `launch_stale`.
    return change_control_launch.approved_matches(original, current)


def _parent(conn, org, brand, campaign, item):
    if item["parent_item_id"]:
        parent = handoff_data.get(conn, org, brand, campaign, item["parent_item_id"])
        if not parent["entity_id"]:
            raise Refused("parent_unread")
        return bindings.entity(conn, org, brand, campaign, parent["entity_id"])
    destination = item["expected_json"].get("destination_entity_id")
    return bindings.entity(conn, org, brand, campaign, destination) if destination else None


def _ownership(conn, org, brand, campaign, node):
    bindings.lock_native(conn, node | {"org_id": org})
    occupied = conn.execute(
        "SELECT brand_id,campaign_id FROM ads_external_entity WHERE org_id=%s AND platform=%s "
        "AND source_account=%s AND native_kind=%s AND native_id=%s",
        (org, node["platform"], node["source_account"], node["native_kind"], node["native_id"]),
    ).fetchall()
    if any(r["brand_id"] != brand or r["campaign_id"] != campaign for r in occupied):
        raise Refused("owned_elsewhere")
    if node["parent_native_id"] is None:
        legacy = conn.execute(
            "SELECT c.id,c.brand_id FROM ads_campaign c WHERE c.org_id=%s AND c.origin='internal' "
            "AND c.external_id=%s AND (NOT EXISTS (SELECT 1 FROM ads_external_entity e "
            "WHERE e.campaign_id=c.id AND e.parent_native_id IS NULL) OR EXISTS "
            "(SELECT 1 FROM ads_external_entity e WHERE e.campaign_id=c.id "
            "AND e.platform=%s AND e.source_account=%s AND e.parent_native_id IS NULL))",
            (org, node["native_id"], node["platform"], node["source_account"]),
        ).fetchall()
        if any(r["id"] != campaign or r["brand_id"] != brand for r in legacy):
            raise Refused("owned_by_plan")


def _source_rows(conn, org, brand, campaign, platform, account, native_ids, *, lock=False):
    rows = conn.execute(
        "WITH RECURSIVE chain AS (SELECT id,parent_native_kind,parent_native_id "
        "FROM ads_external_entity WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND platform=%s AND source_account=%s AND native_id=ANY(%s) UNION "
        "SELECT p.id,p.parent_native_kind,p.parent_native_id FROM ads_external_entity p "
        "JOIN chain c ON p.native_kind=c.parent_native_kind AND p.native_id=c.parent_native_id "
        "WHERE p.org_id=%s AND p.brand_id=%s AND p.campaign_id=%s "
        "AND p.platform=%s AND p.source_account=%s) "
        "SELECT e.* FROM ads_external_entity e WHERE e.id IN (SELECT id FROM chain) "
        "ORDER BY e.id LIMIT 102" + (" FOR UPDATE NOWAIT" if lock else ""),
        (org, brand, campaign, platform, account, native_ids,
         org, brand, campaign, platform, account),
    ).fetchall()
    if len(rows) > 101:
        raise Refused("chain_mismatch")
    lookup = {(row["native_kind"], row["native_id"]): row for row in rows}
    for row in rows:
        node, visited = row, set()
        while node["parent_native_id"] is not None:
            if node["id"] in visited or len(visited) >= 100:
                raise Refused("chain_mismatch")
            visited.add(node["id"])
            node = lookup.get((node["parent_native_kind"], node["parent_native_id"]))
            if node is None:
                raise Refused("chain_mismatch")
    return rows


def _source_versions(conn, org, brand, campaign, platform, account, native_ids, *, lock=False):
    rows = _source_rows(conn, org, brand, campaign, platform, account, native_ids)
    if lock:
        # Do not wait on a parent lease while holding the source rows its writer needs.
        for row in rows:
            if not bindings.lock_native(conn, row, wait=False):
                raise Refused("source_changed")
        rows = _source_rows(conn, org, brand, campaign, platform, account, native_ids, lock=True)
        for row in rows:
            if not bindings.lock_native(conn, row, wait=False):
                raise Refused("source_changed")
    return {row["id"]: str(row["updated_at"]) for row in rows}


_COPY_LABELS = {"title": "標題", "body": "文案", "description": "說明"}
_FIELD_LABELS = {
    "objective": "目標",
    "budget_type": "預算類型",
    "budget_amount": "每日預算",
    "start_date": "開始日期",
    "end_date": "結束日期",
}
_SETTING_LABELS = {f["key"]: f["label"] for f in manual_settings.FIELDS}
# F49 Contract B (decision 5): the ad's material is declared `readable: False` -- a read proves it
# only through the media evidence (`media_verified`, the exact／equivalent media match); otherwise
# approving the launch was its confirmation, never a per-field eye check after launch.
MATERIAL_KEY, MATERIAL_LABEL = "material", "圖片或影片版本"
_PROVEN_MATERIAL = frozenset({"media_verified"})
# F49 Contract B: a group's manual setting the readback compares on each of the group's ads (the
# ad's creative carries the link), not on the ad set.
_COMPARED_ON_ADS = frozenset({"landing_url"})


def approval_confirms(snapshot) -> list[dict]:
    """`[{key, label}]` -- the declared-unreadable fields a launch of `snapshot` (a launch
    snapshot, `change_control_launch.snapshot`) carries: approving it is their one confirmation
    (decision 5). The group keys are the ones `handoff_data.install_launch` freezes for readback."""
    groups = snapshot.get("groups") or []
    found = []
    if groups:
        found.extend(
            {"key": "manual_settings." + key, "label": _SETTING_LABELS.get(key, key)}
            for key in handoff_data.LAUNCH_MANUAL_KEYS
            if key in manual_settings.DECLARED_UNREADABLE
        )
    if any(group.get("ads") for group in groups):
        found.append({"key": MATERIAL_KEY, "label": MATERIAL_LABEL})
    return found


def _plain(value):
    return value if value is None or isinstance(value, (str, int, float, bool)) else str(value)


_CLICK_IDS = frozenset({"fbclid", "gclid"})


def same_landing(planned, link) -> bool:
    """F49 Contract B: one landing page -- same host (lowercased, `www.` ignored, port kept) and
    path (trailing slash ignored), the query compared without `utm_*`／`fbclid`／`gclid` and in
    any order; the scheme and fragment are ignored."""

    def normal(value):
        text = str(value).strip()
        parts = urlsplit(text if "//" in text else "//" + text)
        host = (parts.hostname or "").removeprefix("www.")
        query = sorted(
            (key, val)
            for key, val in parse_qsl(parts.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in _CLICK_IDS
        )
        return host, parts.port, parts.path.rstrip("/"), query

    return normal(planned) == normal(link)


def _settings(item, node, material, observed=None, pixels=None):
    expected = item["expected_json"]
    known, missing, differences = {}, [], []
    # F30 Contract G: the same results keyed for the launch view -- a required field the read
    # cannot see (`unreadable`, confirmed by eye per key) and a differing one with the value the
    # platform showed (`mismatches`, stored with the check). F49 Contract B: a field declared
    # unreadable (decision 5) is never `unreadable` -- it goes to `confirmed_at_approval`, and the
    # item's state is computed over the readable fields only.
    unreadable, mismatches, at_approval = [], [], []
    # F49 Contract B: a compared field the read did not carry this time (`unproven`, the item
    # stays `unknown` with the reason, no eye check) and the first reason code met.
    unproven, codes = [], []

    def unread(key, label, text):
        missing.append(text)
        unreadable.append({"key": key, "label": label})

    def approved(key, label):
        at_approval.append({"key": key, "label": label})

    def not_read(key, label, code):
        missing.append(label)
        unproven.append({"key": key, "label": label, "reason_code": code})
        codes.append(code)

    def differ(key, label, text, want, got):
        differences.append(text)
        mismatches.append(
            {"key": key, "label": label, "expected": _plain(want), "observed": _plain(got)}
        )

    # F29 Contract I: the frozen launch settings against the reader's own observation. A differing
    # value is a deviation; an unreadable one stays out of the item's result (the readback shows
    # it and the user may confirm it by eye).
    compared = launch_settings.compare_item(expected.get("launch_settings"), observed, pixels)
    labels = dict(launch_settings.READBACK_FIELDS)
    for key, result in compared.items():
        if result["state"] == "differ":
            differ(
                "launch_settings." + key,
                labels[key],
                "投放設定：" + labels[key],
                launch_settings.expected_label(key, expected["launch_settings"], pixels),
                result["observed_label"],
            )
    if item["planned_kind"] == "ad":
        fields = changes.copy_fields(node)
        creative = (node.get("creative") or {}).get("fields") or {}
        link = (creative.get("object_story_spec") or {}).get("link_data") or {}
        fields["description"] = creative.get("description", link.get("description"))
        expected_fields = expected.get("copy") or {"body": expected.get("copy_text")}
        for key, value in expected_fields.items():
            if not value:
                continue
            label = _COPY_LABELS.get(key, key)
            if fields.get(key) is None:
                unread("copy." + key, label, "文案：" + key)
            elif fields[key] != value:
                differ("copy." + key, label, "文案：" + key, value, fields[key])
            else:
                known[key] = value
        if not any(expected_fields.values()):
            unread("copy", "核准文案內容", "核准文案內容")
        if material in _PROVEN_MATERIAL:
            known[MATERIAL_KEY] = material
        else:
            approved(MATERIAL_KEY, MATERIAL_LABEL)
        # F49 Contract B: the group's planned landing URL against every link the creative sends
        # people to (the platform's creative shape is the adapter's).
        planned_url = expected.get("landing_url")
        if planned_url:
            key, label = "landing_url", _SETTING_LABELS["landing_url"]
            links = adapters.creative_links(node)
            if not links:
                not_read(key, label, "landing_url_unread")
            elif other := next((u for u in links if not same_landing(planned_url, u)), None):
                differ(key, label, label, planned_url, other)
                codes.append("landing_url_mismatch")
            else:
                known[key] = planned_url
    else:
        for key, value in expected.items():
            if key == "launch_settings":
                continue
            label = _FIELD_LABELS.get(key, key)
            if key == "manual_settings":
                # No existing reader contract proves these semantic/manual fields: a declared one
                # was confirmed at approval, any other is confirmed by eye.
                for k, planned in value.items():
                    setting = "manual_settings." + k
                    if k in _COMPARED_ON_ADS:
                        continue
                    if k == "audience_id":
                        ids = adapters.audience_ids(node)
                        name = _SETTING_LABELS[k]
                        if ids is None:
                            not_read(setting, name, "audience_unread")
                        elif str(planned) not in ids:
                            differ(setting, name, name, planned, "、".join(ids) or None)
                            codes.append("audience_mismatch")
                        else:
                            known[k] = planned
                    elif k in manual_settings.DECLARED_UNREADABLE:
                        approved(setting, _SETTING_LABELS.get(k, k))
                    else:
                        unread(setting, _SETTING_LABELS.get(k, k), "人工設定：" + k)
            elif value is None or node.get(key) is None:
                unread(key, label, key)
            elif str(node[key]) != str(value):
                if key == "budget_amount" and float(node[key]) == float(value):
                    known[key] = value
                elif key == "objective":
                    # The plan holds this product's own objective label, the platform its own code
                    # ("購買" vs "OUTCOME_SALES"): fall back to comparing the families, or every
                    # real campaign reads back deviated (drill 5). Either side unrecognised ->
                    # unproven, never a deviation.
                    planned = campaigns.objective_family(value)
                    family = adapters.objective_family(node.get("platform"), node.get("objective"))
                    if planned == "other" or family == "other":
                        unread(key, label, key)
                    elif planned != family:
                        differ(key, label, key, value, node.get("objective"))
                    else:
                        known[key] = value
                else:
                    differ(key, label, key, value, node[key])
            else:
                known[key] = value
    state = "deviated" if differences else "unknown" if missing else "confirmed"
    extra = {"launch_settings": compared} if compared else {}
    if codes:
        extra |= {"reason_code": codes[0]}
    return state, extra | {
        "setting_matches": False if differences else None if missing else True,
        "matched_fields": list(known),
        "unknown_fields": missing,
        "deviated_fields": differences,
        "unreadable": unreadable,
        "confirmed_at_approval": at_approval,
        "unproven": unproven,
        "mismatches": mismatches,
        "material_evidence": material,
        "entity_exists": True,
        "delivery_confirmed": False,
        "message": reason_text(codes[0])
        if codes and state != "confirmed"
        else "只記本次物件與設定核對；不代表已投遞、素材因果或成效改善。",
    }


def _resolve(status, evidence):
    """An item whose readable fields all match is confirmed once the user confirmed every field
    the read could not see (F30 Contract G: the settings-readback self-confirm rule, per item)."""
    unreadable = evidence.get("unreadable") or []
    confirmed = evidence.get("confirmed") or {}
    if (
        status == "unknown"
        and evidence.get("entity_exists") is True
        and not evidence.get("deviated_fields")
        and not evidence.get("unproven")
        and unreadable
        and all(u["key"] in confirmed for u in unreadable)
    ):
        return "confirmed", evidence | {
            "setting_matches": True,
            "message": "讀得到的欄位都相符，讀不到的由你確認一樣；不代表已投遞或成效改善。",
        }
    return status, evidence


def _aggregate(conn, org, action_id, item_id, message, observed):
    """Write the action's state from its items (the one aggregate) and return it."""
    item = conn.execute(
        "SELECT brand_id,campaign_id,change_set_id FROM ads_handoff_item "
        "WHERE org_id=%s AND action_id=%s AND id=%s", (org, action_id, item_id)
    ).fetchone()
    if item is None:
        raise ValueError("找不到此操作的交接項目。")
    peers = handoff_data.approved_peers(
        conn, org, item["brand_id"], item["campaign_id"], item["change_set_id"], action_id
    )
    # F49 Contract B: the one aggregate -- a deviated item makes its action deviated.
    aggregate = changes.worst_state(r["status"] for r in peers)
    proofs = [{
        "handoff_item_id": peer["id"], "entity_id": peer["entity_id"],
        "status": peer["status"], **peer["evidence_json"],
    } for peer in peers]
    observed_at = max((p["observed_at"] for p in proofs if p.get("observed_at")), default=None)
    attempted_at = max((p["attempted_at"] for p in proofs if p.get("attempted_at")), default=None)
    first = min((p["observed_at"] for p in peers if p["observed_at"]), default=None)
    prior = any(p.get("previous_observation") for p in proofs)
    message = ("本次讀回未完成；保留前次核對證據供查看，請稍後重試。 " + message
               if prior else message)
    conn.execute(
        "UPDATE ads_action SET verification_state=%s,evidence_json=%s,"
        "first_observed_at=COALESCE(first_observed_at,%s),verified_at=%s "
        "WHERE org_id=%s AND brand_id=%s AND campaign_id=%s AND change_set_id=%s AND id=%s",
        (
            aggregate,
            db.jsonb(
                {
                    "handoff_item_id": item_id,
                    "setting_matches": True if aggregate == "confirmed" else
                    False if aggregate == "deviated" else None,
                    "delivery_confirmed": False,
                    "platform_written": False,
                    "message": message,
                    "observed_at": observed_at,
                    "attempted_at": attempted_at,
                    "peers": proofs,
                    "settings": [{"handoff_item_id": p["handoff_item_id"],
                                  **{key: p.get(key) for key in (
                                      "matched_fields", "mismatches", "unreadable", "confirmed",
                                      "confirmed_at_approval", "launch_settings")}}
                                 for p in proofs],
                    "material": [{"handoff_item_id": p["handoff_item_id"],
                                  "evidence_level": p.get("material_evidence", "unknown")}
                                 for p in proofs],
                }
            ),
            first,
            observed_at if aggregate == "confirmed" else None,
            org, item["brand_id"], item["campaign_id"], item["change_set_id"], action_id,
        ),
    )
    return aggregate


def _resolve_queue_row(conn, org, brand, action_id, state):
    """F49 Contract Q: once an action's readback `confirmed` has committed, the queue row its set
    answers leaves the inbox if it is done now (`triage.resolve_action`; each resolve commits)."""
    if state != "confirmed":
        return
    from app.ads import triage

    triage.resolve_action(conn, org, brand, action_id)


def _finish(conn, org, brand, campaign, item_id, attempt, status, evidence, entity_id=None):
    changes.lock(conn, org, brand)
    current = handoff_data.get(conn, org, brand, campaign, item_id)
    if current["attempt_id"] != attempt:
        conn.commit()
        return current
    change_set = changes.get(conn, org, brand, campaign, current["change_set_id"])
    if change_set["status"] != "approved":
        conn.commit()
        return current
    observed = evidence.get("entity_exists") is True
    evidence["attempted_at"] = db.now_utc().isoformat()
    if not observed:
        prior_evidence = current["evidence_json"]
        previous = prior_evidence.get("previous_observation")
        if prior_evidence.get("observed_at") and current["observed_at"]:
            previous = {
                "observed_at": current["observed_at"].isoformat(),
                "evidence": {key: value for key, value in prior_evidence.items()
                             if key != "previous_observation"},
            }
        if previous:
            evidence["previous_observation"] = previous
    # Per-field confirmations outlive a fresh read, as `settings_confirmed` does.
    prior = current["evidence_json"].get("confirmed")
    if prior and "confirmed" not in evidence:
        evidence["confirmed"] = prior
    status, evidence = _resolve(status, evidence)
    conn.execute(
        "UPDATE ads_handoff_item SET status=%s,evidence_json=%s,entity_id=COALESCE(%s,entity_id),"
        "observed_at=COALESCE(%s::timestamptz,observed_at),updated_at=now() "
        "WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND id=%s AND attempt_id=%s",
        (status, db.jsonb(evidence), entity_id, evidence.get("observed_at"),
         org, brand, campaign, item_id, attempt),
    )
    current = handoff_data.get(conn, org, brand, campaign, item_id)
    aggregate = None
    if current["attempt_id"] == attempt:
        aggregate = _aggregate(conn, org, current["action_id"], item_id, evidence["message"],
                               observed)
    conn.commit()
    _resolve_queue_row(conn, org, brand, current["action_id"], aggregate)
    return handoff_data.get(conn, org, brand, campaign, item_id)


def _confirmable(conn, org, brand, campaign, item_id, key):
    changes.lock(conn, org, brand)
    item = handoff_data.get(conn, org, brand, campaign, item_id)
    evidence = item["evidence_json"]
    keys = {u["key"] for u in evidence.get("unreadable") or []}
    if (
        item["status"] not in {"unknown", "deviated"}
        or key not in keys
        or key in (evidence.get("confirmed") or {})
    ):
        raise ValueError("只有讀不到的欄位可以由你確認一樣。")
    return item


def confirm_field(conn, org, brand, campaign, item_id, key, actor):
    """F30 Contract G `POST …/launch/items/{id}/confirm {key}`: the user looked at the platform
    and says a field the read could not see is the same. Refused for any other field; nothing is
    written to a platform."""
    item = _confirmable(conn, org, brand, campaign, item_id, key)
    material = None
    if key == "material" and item["placement_id"] and item["entity_id"]:
        # Confirming the material by eye upgrades the binding as the check path does. The eye
        # confirmation exists for reads that fail, so a failed re-check keeps the confirmation
        # and only leaves the evidence level where it was.
        try:
            material = asset_binding.verify(
                conn, org, brand, campaign, item["placement_id"], item["placement_revision"],
                item["entity_id"], actor, user_verified=True,
            )["evidence_level"]
        except ValueError:
            material = None
        # verify commits around its provider read: lock and check the item again.
        item = _confirmable(conn, org, brand, campaign, item_id, key)
    evidence = dict(item["evidence_json"])
    if material:
        evidence["material_evidence"] = material
    confirmed = dict(evidence.get("confirmed") or {})
    confirmed[key] = {"at": db.now_utc().isoformat(), "by": actor}
    status, evidence = _resolve(item["status"], evidence | {"confirmed": confirmed})
    conn.execute(
        "UPDATE ads_handoff_item SET status=%s,evidence_json=%s,updated_at=now() "
        "WHERE org_id=%s AND brand_id=%s AND campaign_id=%s AND id=%s",
        (status, db.jsonb(evidence), org, brand, campaign, item_id),
    )
    aggregate = None
    if status != item["status"]:
        aggregate = _aggregate(conn, org, item["action_id"], item_id, evidence["message"], True)
    conn.commit()
    _resolve_queue_row(conn, org, brand, item["action_id"], aggregate)
    return handoff_data.get(conn, org, brand, campaign, item_id)


def _selected_identity(conn, org, brand, campaign, item):
    """Reuse an explicit handoff identity or a unique current placement binding, never names."""
    if item["entity_id"]:
        return bindings.entity(conn, org, brand, campaign, item["entity_id"])
    candidates = bindings.list_bindings(
        conn, org, brand, campaign, item["placement_id"], item["placement_revision"]
    )
    current = {row["entity_id"] for row in candidates
               if row["entity_id"] and row["valid_to"] is None}
    if len(candidates) >= 100 or len(current) > 1:
        raise Refused("identity_ambiguous")
    if not current:
        raise Refused("identity_unselected")
    return bindings.entity(conn, org, brand, campaign, current.pop())


def _material_current(conn, org, brand, campaign, item):
    if item["placement_id"]:
        _coded("plan_changed", bindings.confirmed, conn, org, brand, campaign,
               item["placement_id"], item["placement_revision"], write=True)


def check_action(conn, org, brand, campaign, set_id, action_id, actor):
    """Payload-free change-item rereads reuse the approved handoff comparator."""
    changes.lock(conn, org, brand)
    peers = handoff_data.approved_peers(conn, org, brand, campaign, set_id, action_id)
    if not peers:
        conn.rollback()
        raise ValueError("此操作沒有已核准的交接項目，請重新載入交接清單。")
    for peer in peers:
        changes.lock(conn, org, brand)
        action_set = changes.get(conn, org, brand, campaign, set_id)
        action = next(row for row in action_set["items"] if row["id"] == action_id)
        if action_set["status"] != "approved" or action["verification_state"] == "stale":
            conn.commit()
            return action_set
        peer = handoff_data.get(conn, org, brand, campaign, peer["id"])
        try:
            _material_current(conn, org, brand, campaign, peer)
            identity = _selected_identity(conn, org, brand, campaign, peer)
        except ValueError as exc:
            attempt = db.new_id("ahc")
            conn.execute("UPDATE ads_handoff_item SET attempt_id=%s WHERE id=%s",
                         (attempt, peer["id"]))
            code, text = refusal(exc)
            _finish(conn, org, brand, campaign, peer["id"], attempt,
                    "stale" if code == "plan_changed" else "unknown", {
                        "message": text, "reason_code": code, "entity_exists": False,
                        "setting_matches": None, "material_evidence": "unknown",
                        "delivery_confirmed": False, "attempt_id": attempt,
                    })
            continue
        payload = {key: identity[key]
                   for key in ("platform", "source_account", "native_kind", "native_id")}
        check(conn, org, brand, campaign, peer["id"], payload, actor)
    return changes.get(conn, org, brand, campaign, set_id)


def _guard_read(conn, org, brand, campaign, item, attempt, parent, payload, source_ids,
                source_versions, *, entity_id=None):
    """Reacquire owner locks after HTTP, before any source proof can be persisted."""
    changes.lock(conn, org, brand)
    latest = handoff_data.get(conn, org, brand, campaign, item["id"])
    if latest["attempt_id"] != attempt:
        raise Refused("source_changed")
    current_set = changes.get(conn, org, brand, campaign, item["change_set_id"])
    if current_set["status"] != "approved":
        raise Refused("not_approved")
    action = next(row for row in current_set["items"] if row["id"] == item["action_id"])
    if action["kind"] == "new_ad" and action["verification_state"] == "stale":
        raise Refused("plan_changed")
    _material_current(conn, org, brand, campaign, latest)
    if (latest["expected_json"], latest["placement_id"], latest["placement_revision"]) != (
        item["expected_json"], item["placement_id"], item["placement_revision"]
    ):
        raise Refused("plan_changed")
    if entity_id is not None and latest["entity_id"] != entity_id:
        raise Refused("identity_taken")
    # Sync creative writers hold this lease without the brand/placement locks. Wait first,
    # then lock every existing source row so structure writers cannot move a parent afterward.
    bindings.lock_native(conn, {"org_id": org, **payload})
    try:
        current_source_versions = _source_versions(
            conn, org, brand, campaign, payload["platform"], payload["source_account"],
            source_ids, lock=True
        )
    except LockNotAvailable as exc:
        raise Refused("source_changed") from exc
    latest_parent = _parent(conn, org, brand, campaign, latest)
    keys = ("id", "platform", "source_account", "native_kind", "native_id")
    if tuple((latest_parent or {}).get(key) for key in keys) != tuple(
        (parent or {}).get(key) for key in keys
    ):
        raise Refused("parent_mismatch")
    if source_versions is not None and source_versions != current_source_versions:
        raise Refused("source_changed")
    if not _launch_current(conn, org, brand, campaign, current_set):
        raise Refused("plan_changed")


def check(conn, org, brand, campaign, item_id, payload, actor):
    changes.lock(conn, org, brand)
    item = handoff_data.get(conn, org, brand, campaign, item_id)
    change_set = changes.get(conn, org, brand, campaign, item["change_set_id"])
    if change_set["status"] != "approved":
        raise Refused("not_approved")
    parent = _parent(conn, org, brand, campaign, item)
    if parent and (payload["platform"], payload["source_account"]) != (
        parent["platform"],
        parent["source_account"],
    ):
        raise Refused("account_mismatch")
    if item["entity_id"] and (
        payload["platform"],
        payload["source_account"],
        payload["native_kind"],
        payload["native_id"],
    ) != (item["platform"], item["source_account"], item["native_kind"], item["native_id"]):
        raise Refused("identity_taken")
    if item["expected_json"].get("source_entity_id"):
        source = bindings.entity(
            conn, org, brand, campaign, item["expected_json"]["source_entity_id"]
        )
        if (
            payload["platform"],
            payload["source_account"],
            payload["native_kind"],
            payload["native_id"],
        ) == (
            source["platform"],
            source["source_account"],
            source["native_kind"],
            source["native_id"],
        ):
            raise Refused("original_as_new")
    if payload["native_id"] in item["expected_json"].get("existing_native_ids", []):
        raise Refused("preexisting_ad")
    reader, account = external_sync.account_reader(
        conn, org, brand, payload["platform"], payload["source_account"]
    )
    if item["planned_kind"] == "ad" and payload["native_kind"] not in reader.binding_kinds():
        raise Refused("wrong_level")
    root = bindings.root(conn, org, brand, campaign, parent) if parent else payload
    source_ids = list(
        {payload["native_id"], root["native_id"], *([parent["native_id"]] if parent else [])}
    )
    source_versions = _source_versions(
        conn, org, brand, campaign, payload["platform"], payload["source_account"], source_ids
    )
    attempt = db.new_id("ahc")
    conn.execute("UPDATE ads_handoff_item SET attempt_id=%s WHERE id=%s", (attempt, item_id))
    conn.commit()
    proof = None
    try:
        action = next(row for row in change_set["items"] if row["id"] == item["action_id"])
        if action["kind"] == "new_ad" and action["verification_state"] == "stale":
            raise Refused("plan_changed")
        _material_current(conn, org, brand, campaign, item)
        conn.commit()
        proof = reader.verify_native(
            conn,
            org,
            brand,
            account,
            native_kind=payload["native_kind"],
            native_id=payload["native_id"],
            root_kind=root["native_kind"],
            root_id=root["native_id"],
            original={},
        )
        _coded("chain_mismatch", asset_binding._validate_chain, proof, payload, root)
        node = proof["entity"]
        observed = node.get("launch_settings")
        if parent and (node.get("parent_native_kind"), node.get("parent_native_id")) != (
            parent["native_kind"],
            parent["native_id"],
        ):
            raise Refused("parent_mismatch")
        if not parent and node.get("parent_native_id") is not None:
            raise Refused("root_required")
        external_sync.account_reader(
            conn, org, brand, payload["platform"], payload["source_account"]
        )
        _guard_read(conn, org, brand, campaign, item, attempt, parent, payload,
                    source_ids, source_versions)
        nodes = [
            ExternalEntity.model_validate(
                {k: v for k, v in raw.items() if k in ExternalEntity.model_fields}
            ).model_dump()
            for raw in [node, *proof["parents"]]
        ]
        for raw in nodes:
            _ownership(conn, org, brand, campaign, raw)
        for raw in reversed(nodes):
            saved = external.upsert_entity(conn, org, brand, campaign, raw)
            if raw is nodes[0]:
                entity_id = saved["id"]
        occupied = conn.execute(
            "SELECT id FROM ads_handoff_item WHERE org_id=%s AND entity_id=%s AND id<>%s",
            (org, entity_id, item_id),
        ).fetchone()
        if occupied:
            raise Refused("item_taken")
        if change_set["plan_json"].get("launch_snapshot"):
            bind = {
                "campaign": campaigns.bind_campaign,
                "group": campaigns.bind_group,
                "ad": campaigns.bind_ad,
            }[item["planned_kind"]]
            bind(
                conn,
                org,
                brand,
                item["planned_id"],
                external_id=node["native_id"],
                external_name=node.get("name") or node["native_id"],
                external_status=node.get("native_status"),
            )
        conn.execute(
            "UPDATE ads_handoff_item SET entity_id=%s WHERE id=%s AND attempt_id=%s",
            (entity_id, item_id, attempt),
        )
        conn.commit()
        material = "user_verified" if payload.get("user_verified") else "unknown"
        if item["placement_id"]:
            # The first read persisted its own source rows. Freeze the second HTTP's basis now.
            material_source_versions = _source_versions(
                conn, org, brand, campaign, payload["platform"], payload["source_account"],
                source_ids
            )

            def before_material_persist():
                _guard_read(conn, org, brand, campaign, item, attempt, parent, payload,
                            source_ids, material_source_versions, entity_id=entity_id)

            binding = _coded(
                "material_unverified",
                asset_binding.verify,
                conn,
                org,
                brand,
                campaign,
                item["placement_id"],
                item["placement_revision"],
                entity_id,
                actor,
                user_verified=payload.get("user_verified", False),
                before_persist=before_material_persist,
            )
            material = binding["evidence_level"]
            # The verifier commits its source proof. Keep the action premise locked to finish.
            _guard_read(conn, org, brand, campaign, item, attempt, parent, payload,
                        source_ids, None, entity_id=entity_id)
            node = bindings.entity(conn, org, brand, campaign, entity_id)
        pixels = launch_settings.cached_pixels(
            campaigns.get_campaign(conn, org, brand, campaign) or {}
        )
        status, evidence = _settings(item, node, material, observed, pixels)
        evidence.update(
            observed_at=db.now_utc().isoformat(),
            native_id=node["native_id"],
            source_account=node["source_account"],
            attempt_id=attempt,
        )
        return _finish(conn, org, brand, campaign, item_id, attempt, status, evidence, entity_id)
    except ValueError as exc:
        # F49 Contract B: a refusal only -- a code bug (AttributeError, …) propagates instead of
        # reading as "wrong object picked". The evidence names why, by code and sentence.
        conn.rollback()
        code, text = refusal(exc)
        return _finish(
            conn,
            org,
            brand,
            campaign,
            item_id,
            attempt,
            "stale" if code == "plan_changed" else "unknown",
            {
                "message": text,
                "reason_code": code,
                "entity_exists": False,
                "setting_matches": None,
                "material_evidence": "unknown",
                "delivery_confirmed": False,
                "attempt_id": attempt,
            },
        )


# -- F29 Contract I: launch-settings readback ------------------------------------------------------


def _readback_set(conn, org, brand, campaign):
    change_set = change_control_launch.launch_set(conn, org, brand, campaign)
    if change_set is None:
        return None, None
    frozen = change_set["plan_json"]["launch_snapshot"].get("launch_settings")
    return change_set, frozen


def settings_readback(conn, org, brand, campaign):
    """`settings_readback` of `GET …/handoff`: every launch-settings field of the current approved
    launch against what the readbacks observed. A field any ad set (or ad, for UTM) differs on is
    `differ`; one no read returned is `unreadable` with its reason (or `self_confirmed` once the
    user confirmed it by eye). None before any ad set or ad was read back, or for a launch approved
    before launch settings existed."""
    change_set, frozen = _readback_set(conn, org, brand, campaign)
    if change_set is None or frozen is None:
        return None
    rows = conn.execute(
        "SELECT evidence_json,observed_at FROM ads_handoff_item WHERE org_id=%s AND brand_id=%s "
        "AND campaign_id=%s AND change_set_id=%s AND planned_kind IN ('group','ad') "
        "AND evidence_json ? 'launch_settings'",
        (org, brand, campaign, change_set["id"]),
    ).fetchall()
    if not rows:
        return None
    pixels = launch_settings.cached_pixels(campaigns.get_campaign(conn, org, brand, campaign) or {})
    confirmed = change_set["plan_json"].get("settings_confirmed") or {}
    fields = []
    for key, label in launch_settings.READBACK_FIELDS:
        results = [
            r["evidence_json"]["launch_settings"][key]
            for r in rows
            if key in (r["evidence_json"].get("launch_settings") or {})
        ]
        differ = next((r for r in results if r["state"] == "differ"), None)
        unreadable = next((r for r in results if r["state"] == "unreadable"), None)
        if differ:
            state, observed, reason = "differ", differ["observed_label"], None
        elif unreadable or not results:
            state = "self_confirmed" if key in confirmed else "unreadable"
            observed = None
            reason = unreadable["reason"] if unreadable else "還沒讀回這一項。"
        else:
            state, observed, reason = "match", results[0]["observed_label"], None
        fields.append(
            {
                "key": key,
                "label": label,
                "expected_label": launch_settings.expected_label(key, frozen, pixels),
                "observed_label": observed,
                "state": state,
                "reason": reason,
            }
        )
    read_at = max((r["observed_at"] for r in rows if r["observed_at"]), default=None)
    return {"read_at": read_at, "fields": fields}


def confirm_setting(conn, org, brand, campaign, key, actor):
    """`POST …/handoff/launch/settings-confirm {key}`: the user looked at the platform and says an
    unreadable field is the same. Refused for any other state; nothing is written to a platform."""
    changes.lock(conn, org, brand)
    readback = settings_readback(conn, org, brand, campaign)
    field = next((f for f in (readback or {}).get("fields", []) if f["key"] == key), None)
    if field is None or field["state"] != "unreadable":
        raise ValueError("只有讀不到的投放設定可以由你確認一樣。")
    change_set, _ = _readback_set(conn, org, brand, campaign)
    assert change_set is not None
    conn.execute(
        "UPDATE ads_change_set SET plan_json=jsonb_set(plan_json,'{settings_confirmed}',"
        "COALESCE(plan_json->'settings_confirmed','{}'::jsonb) || %s::jsonb) "
        "WHERE org_id=%s AND brand_id=%s AND campaign_id=%s AND id=%s",
        (
            db.jsonb({key: {"at": db.now_utc().isoformat(), "by": actor}}),
            org,
            brand,
            campaign,
            change_set["id"],
        ),
    )
    conn.commit()
    return handoff_data.workspace(conn, org, brand, campaign)


def confirm_all(conn, org, brand, campaign, actor):
    """`POST …/handoff/launch/confirm-all` (drill-7 #18: 27 unreadable fields clicked one by one):
    the user looked at the platform once and says every field the read could not see is the same.
    Every launch item field and every launch setting the readback still reports as unreadable goes
    through `confirm_field` / `confirm_setting`; readable, already confirmed and differing fields
    are skipped, never refused. Each of those two commits as it does on its own, so a call cut
    short is finished by the next one (every step is idempotent). Answers with the counts and the
    same payload `GET …/launch` returns; nothing is written to a platform."""
    changes.lock(conn, org, brand)
    change_set, _ = _readback_set(conn, org, brand, campaign)
    items = 0
    if change_set is not None:
        rows = conn.execute(
            "SELECT id,evidence_json FROM ads_handoff_item WHERE org_id=%s AND brand_id=%s "
            "AND campaign_id=%s AND change_set_id=%s AND status IN ('unknown','deviated') "
            "ORDER BY created_at,id",
            (org, brand, campaign, change_set["id"]),
        ).fetchall()
        for row in rows:
            evidence = row["evidence_json"] or {}
            confirmed = evidence.get("confirmed") or {}
            for field in evidence.get("unreadable") or []:
                if field["key"] in confirmed:
                    continue
                confirm_field(conn, org, brand, campaign, row["id"], field["key"], actor)
                items += 1
    readback = settings_readback(conn, org, brand, campaign) or {}
    settings = 0
    for field in readback.get("fields", []):
        if field["state"] == "unreadable":
            confirm_setting(conn, org, brand, campaign, field["key"], actor)
            settings += 1
    # Lazy import: `launch_view` reads this module (cycle), and the view it builds is the answer.
    from app.ads import launch_view

    return {
        "confirmed_items": items,
        "confirmed_settings": settings,
        "view": launch_view.view(conn, org, brand, campaign),
    }
