"""Append-only campaign material requests; pure saving never calls a model."""

import json
import logging
from contextlib import contextmanager

from app import workbench
from app.ads import asset_binding_repository as bindings
from app.ads import change_control_data as common
from app.ads import review_rounds
from app.ads import user_assets_repository as assets
from app.core import db

logger = logging.getLogger(__name__)

MODES = {"existing", "external_image", "workbench_image", "copy"}
EDITABLE = {"title", "instruction", "copy_fields", "prompt", "reference_asset_ids"}
LIMITATIONS = [
    "提示詞、參考圖與回收成品的關係由使用者記錄，不代表已驗證外部生成過程。",
    "選定只保存本機素材安排，不代表已上架、已投遞或已證明成效。",
    "未提供提示詞或參考圖時保留未知；候選檔案不會自動送給模型分析。",
]


@contextmanager
def _locked(conn, org, brand):
    # Existing workbench writes commit internally. Session lock survives those commits.
    key = f"ads-material:{org}:{brand}"
    conn.execute("SELECT pg_advisory_lock(hashtextextended(%s,0))", (key,))
    try:
        yield
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (key,))


def _campaign(conn, org, brand, campaign, *, mutable=False):
    value = common.campaign(conn, org, brand, campaign)
    if mutable and value["status"] == "closed":
        raise ValueError("活動已結案，素材歷史仍可查看。")
    return value


def _text(value, maximum, *, required=False):
    if not isinstance(value, str) or len(value) > maximum or required and not value.strip():
        raise ValueError("請填寫有效的任務名稱或指示，並遵守長度限制。")
    return value.strip()


def _references(conn, org, brand, value):
    if not isinstance(value, list) or len(value) > 10 or any(not isinstance(v, str) for v in value):
        raise ValueError("每次最多選擇十個品牌參考圖原檔。")
    if len(set(value)) != len(value):
        raise ValueError("參考圖不可重複。")
    for asset_id in value:
        row = assets.get_asset(conn, org, brand, asset_id)
        if not row["mime_type"].startswith("image/"):
            raise ValueError("參考圖需為已保存的圖片原檔。")
    return value


def _prompt(conn, org, brand, value):
    if not isinstance(value, dict) or set(value) - {
        "source",
        "text",
        "set_id",
        "version_id",
        "card_index",
        "origin",
    }:
        raise ValueError("提示詞來源格式無效。")
    source = value.get("source", "none")
    if source == "none":
        if any(v not in (None, "") for k, v in value.items() if k != "source"):
            raise ValueError("有提示詞內容時請明確選擇來源。")
        return {"source": "none", "text": None}
    if source == "manual":
        return {
            "source": "manual",
            "text": _text(value.get("text"), 24000, required=True),
            "origin": _text(value.get("origin", ""), 500),
        }
    if source == "workbench":
        return workbench.material_source(
            conn,
            org,
            brand,
            value.get("set_id"),
            value.get("version_id"),
            value.get("card_index"),
        )
    raise ValueError("提示詞來源只能是未提供、手動提供或工作檯版本。")


def _review(conn, org, brand, campaign, payload):
    rid, recid = payload.get("review_id"), payload.get("recommendation_id")
    if not rid and not recid:
        return {"review_id": None, "recommendation_id": None, "review_context": None}
    if not rid or not recid:
        raise ValueError("檢討與建議識別需一起提供。")
    review = review_rounds.get(conn, org, brand, campaign, rid)
    if review["status"] not in {"ready", "completed"}:
        raise ValueError("此檢討尚無可承接的建議。")
    rec = next(
        (r for r in review["result_json"].get("recommendations", []) if r["id"] == recid), None
    )
    if not rec or rec["recommendation"] not in {"adjust", "new_test"}:
        raise ValueError("請選擇調整或下一個測試的建議。")
    if rec["target_id"] != review["entity_id"]:
        raise ValueError("建議與本回檢討的廣告不一致。")
    evidence = review["evidence_json"]
    source_ids = {ref.removeprefix("source:") for ref in rec["evidence_refs"]}
    return {
        "review_id": rid,
        "recommendation_id": recid,
        "review_context": {
            "entity_id": review["entity_id"],
            "hypothesis": rec["hypothesis"],
            "next_step": rec["next_step"],
            "risks": rec["risks"],
            "evidence_refs": rec["evidence_refs"],
            "evidence_hash": review["evidence_hash"],
            "sources": [s for s in evidence.get("sources", []) if s["id"] in source_ids],
            "limitations": evidence.get("limitations", []),
            "window_end": str(review["window_end"]),
        },
    }


def get(conn, org, brand, campaign, task_id, revision=None):
    _campaign(conn, org, brand, campaign)
    row = conn.execute(
        "SELECT t.id,t.campaign_id,t.revision AS current_revision,t.created_at,"
        "t.replaces_entity_id,t.cancelled_at,"
        "r.revision,r.spec_json,r.content_hash,r.pack_id,r.dispatch_status,r.approved_hash"
        " FROM ads_material_task t JOIN ads_material_revision r ON r.task_id=t.id"
        " AND r.revision=COALESCE(%s,t.revision) WHERE t.org_id=%s AND t.brand_id=%s"
        " AND t.campaign_id=%s AND t.id=%s",
        (revision, org, brand, campaign, task_id),
    ).fetchone()
    if not row:
        raise ValueError("找不到此品牌活動的素材任務或版本。")
    result = dict(row)
    result.update(result.pop("spec_json"))
    result["replaces"] = _replaces(conn, org, brand, campaign, result.pop("replaces_entity_id"))
    result["placement_current"] = None
    if result.get("placement_id"):
        p = assets.placement(conn, org, brand, campaign, result["placement_id"])
        result["placement_current"] = p["revision"] == result["placement_revision"]
    result["history"] = [
        dict(r)
        for r in conn.execute(
            "SELECT revision,content_hash,created_at,pack_id,dispatch_status"
            " FROM ads_material_revision"
            " WHERE task_id=%s AND org_id=%s AND brand_id=%s ORDER BY revision DESC LIMIT 100",
            (task_id, org, brand),
        ).fetchall()
    ]
    result["limitations"] = LIMITATIONS
    result["state_label"] = _state_label(conn, org, brand, result)
    return result


def _replaces(conn, org, brand, campaign, entity_id):
    """The ad this request replaces, read live (its name or thumbnail may change after sync)."""
    if entity_id is None:
        return None
    from app.ads import triage

    try:
        ad = bindings.entity(conn, org, brand, campaign, entity_id)
    except ValueError:
        return {"entity_id": entity_id, "name": None, "thumbnail_url": None}
    return {
        "entity_id": entity_id,
        "name": ad.get("name") or ad["native_id"],
        "thumbnail_url": triage._thumbnail_url(ad),
    }


def workspace(conn, org, brand, campaign):
    _campaign(conn, org, brand, campaign)
    rows = conn.execute(
        "SELECT id FROM ads_material_task WHERE org_id=%s AND brand_id=%s AND campaign_id=%s"
        " AND cancelled_at IS NULL ORDER BY created_at DESC,id LIMIT 101",
        (org, brand, campaign),
    ).fetchall()
    return {
        "tasks": [get(conn, org, brand, campaign, r["id"]) for r in rows[:100]],
        "truncated": len(rows) > 100,
    }


REPLACE_REQUESTS_CAP = 100


# F49 Contract T: a material request's state, said once (the task read and the replace requests).
STATE_LABELS = {
    "not_requested": "還沒交棒",
    "unknown": "交棒沒送出・可重試",
    "queued": "工作檯製作中",
    "failed": "工作檯沒做成",
    "candidates": "有候選圖",
    "adopted": "已採用",
}


def _pack_failed(conn, org, brand, task) -> bool:
    """The revision's workbench pack ran and its generation failed (`slots.brief_state`, the one
    reader of a set's status in ads)."""
    from app.ads import slots

    briefs = workbench.briefs_for_source(
        conn, org, brand, "schedule_node",
        {"material_task_id": task["id"], "material_revision": task["revision"]},
    )
    return any(
        b.get("pack_id") == task["pack_id"] and slots.brief_state(b) == "failed" for b in briefs
    )


def _state_label(conn, org, brand, task):
    """The request's own state, newest step first (Contract F): adopted, candidates, then the
    hand-off -- not sent yet, sent but not confirmed enqueued (retryable), the workbench making
    it, or its generation failed. `task` carries `id`, `revision`, `pack_id`, `dispatch_status`
    and the spec's `placement_id`／`selected_candidate_id`／`candidates`."""
    if task.get("placement_id") or task.get("selected_candidate_id"):
        state = "adopted"
    elif task.get("candidates"):
        state = "candidates"
    elif task["dispatch_status"] == "queued" and _pack_failed(conn, org, brand, task):
        state = "failed"
    else:
        state = task["dispatch_status"]
    return STATE_LABELS.get(state, STATE_LABELS["not_requested"])


def replace_requests(conn, org, brand, campaign):
    """Open "replace this ad" requests, newest first: the first 100 as rows (`truncated` past
    that) and `by_entity` (replaced entity -> task id) over all of them -- at most one open
    request per ad (the partial unique index)."""
    rows = conn.execute(
        "SELECT t.id,t.created_at,t.replaces_entity_id,t.revision,r.spec_json,r.pack_id,"
        "r.dispatch_status FROM ads_material_task t"
        " JOIN ads_material_revision r ON r.task_id=t.id AND r.revision=t.revision"
        " WHERE t.org_id=%s AND t.brand_id=%s AND t.campaign_id=%s AND t.cancelled_at IS NULL"
        " AND t.replaces_entity_id IS NOT NULL ORDER BY t.created_at DESC,t.id DESC",
        (org, brand, campaign),
    ).fetchall()
    return {
        "requests": [
            {
                "task_id": r["id"],
                "replaces": _replaces(conn, org, brand, campaign, r["replaces_entity_id"]),
                "created_at": r["created_at"],
                "state_label": _state_label(
                    conn, org, brand,
                    {
                        **r["spec_json"], "id": r["id"], "revision": r["revision"],
                        "pack_id": r["pack_id"], "dispatch_status": r["dispatch_status"],
                    },
                ),
            }
            for r in rows[:REPLACE_REQUESTS_CAP]
        ],
        "truncated": len(rows) > REPLACE_REQUESTS_CAP,
        "by_entity": {r["replaces_entity_id"]: r["id"] for r in rows},
    }


def prompt_options(conn, org, brand, campaign, task_id):
    task = get(conn, org, brand, campaign, task_id)
    return {
        "options": workbench.material_options(
            conn,
            org,
            brand,
            part="copy" if task["mode"] == "copy" else "image_prompt",
        )
    }


def _prior(conn, org, brand, campaign, payload, action, task_id=None):
    operation = common.operation(payload.get("operation_id"))
    digest = common.digest(
        {
            "campaign": campaign,
            "task": task_id,
            "action": action,
            "body": {k: v for k, v in payload.items() if k != "operation_id"},
        }
    )
    prior = conn.execute(
        "SELECT * FROM ads_material_operation WHERE org_id=%s AND brand_id=%s AND operation_id=%s",
        (org, brand, operation),
    ).fetchone()
    if prior and prior["request_hash"] != digest:
        raise ValueError("同一次操作內容不同，請重新整理後使用新的操作識別。")
    return operation, digest, prior


def _remember(conn, org, brand, campaign, operation, digest, task_id, revision):
    conn.execute(
        "INSERT INTO ads_material_operation(org_id,brand_id,operation_id,campaign_id,task_id,"
        "request_hash,result_revision) VALUES(%s,%s,%s,%s,%s,%s,%s)",
        (org, brand, operation, campaign, task_id, digest, revision),
    )


def _write(conn, org, brand, campaign, task_id, revision, spec, *, inherit=None):
    conn.execute(
        "INSERT INTO ads_material_revision(task_id,revision,org_id,brand_id,campaign_id,"
        "content_hash,spec_json) VALUES(%s,%s,%s,%s,%s,%s,%s)",
        (task_id, revision, org, brand, campaign, common.digest(spec), db.jsonb(spec)),
    )
    conn.execute("UPDATE ads_material_task SET revision=%s WHERE id=%s", (revision, task_id))
    if inherit:
        conn.execute(
            "UPDATE ads_material_revision SET pack_id=%s,dispatch_status=%s,approved_hash=%s"
            " WHERE task_id=%s AND revision=%s",
            (
                inherit["pack_id"],
                inherit["dispatch_status"],
                inherit["approved_hash"],
                task_id,
                revision,
            ),
        )


def _replace_target(conn, org, brand, campaign, entity_id):
    ad = bindings.entity(conn, org, brand, campaign, entity_id)
    if ad["native_kind"] != "ad":
        raise ValueError("「換掉這一則」只能指定本活動裡的一則廣告。")
    return ad


def create(conn, org, brand, campaign, payload, actor):
    _campaign(conn, org, brand, campaign, mutable=True)
    if (
        set(payload)
        - EDITABLE
        - {
            "operation_id",
            "mode",
            "review_id",
            "recommendation_id",
            "replaces_entity_id",
        }
    ):
        raise ValueError("素材任務欄位無效。")
    with _locked(conn, org, brand):
        operation, digest, prior = _prior(conn, org, brand, campaign, payload, "create")
        if prior:
            return get(conn, org, brand, campaign, prior["task_id"], prior["result_revision"])
        replaces = payload.get("replaces_entity_id")
        if replaces is not None:
            ad = _replace_target(conn, org, brand, campaign, replaces)
            open_task = conn.execute(
                "SELECT id,revision FROM ads_material_task WHERE org_id=%s AND brand_id=%s"
                " AND campaign_id=%s AND replaces_entity_id=%s AND cancelled_at IS NULL",
                (org, brand, campaign, replaces),
            ).fetchone()
            if open_task:
                # One open request per ad: a repeat click returns the request already raised.
                _remember(
                    conn,
                    org,
                    brand,
                    campaign,
                    operation,
                    digest,
                    open_task["id"],
                    open_task["revision"],
                )
                conn.commit()
                return get(conn, org, brand, campaign, open_task["id"])
            # Unresolved 6 defaults: a one-click request asks the workbench for a new image.
            name = ad.get("name") or ad["native_id"]
            payload = {"mode": "workbench_image", "title": ("換掉：" + name)[:200], **payload}
        if payload.get("mode") not in MODES:
            raise ValueError("請選擇素材來源。")
        spec = {
            "title": _text(payload.get("title"), 200, required=True),
            "mode": payload["mode"],
            "instruction": _text(payload.get("instruction", ""), 8000),
            "copy_fields": assets.validate_copy(payload.get("copy_fields", {})),
            "prompt": _prompt(conn, org, brand, payload.get("prompt", {"source": "none"})),
            "reference_asset_ids": _references(
                conn, org, brand, payload.get("reference_asset_ids", [])
            ),
            "candidates": [],
            "selected_candidate_id": None,
            "placement_id": None,
            "placement_revision": None,
            **_review(conn, org, brand, campaign, payload),
        }
        if spec["prompt"].get("part") == "copy":
            canonical = spec["prompt"]["copy_fields"]
            if "copy_fields" in payload and spec["copy_fields"] != canonical:
                raise ValueError("文案已不同於工作檯原版本，請改為手動來源並保留原版本說明。")
            spec["copy_fields"] = canonical
        task_id = db.new_id("amt")
        conn.execute(
            "INSERT INTO ads_material_task(id,org_id,brand_id,campaign_id,created_by,"
            "replaces_entity_id) VALUES(%s,%s,%s,%s,%s,%s)",
            (task_id, org, brand, campaign, actor, replaces),
        )
        _write(conn, org, brand, campaign, task_id, 1, spec)
        _remember(conn, org, brand, campaign, operation, digest, task_id, 1)
        conn.commit()
        return get(conn, org, brand, campaign, task_id)


def open_task(conn, org, brand, campaign, task_id):
    """The one guard for using a request: edits, dispatch and every change set that cites it
    (new ad, copy) read it here, so a cancelled request can never be carried forward."""
    task = get(conn, org, brand, campaign, task_id)
    if task["cancelled_at"] is not None:
        raise ValueError("此素材需求已取消，請另開新的需求或重新選定素材。")
    return task


def _base(conn, org, brand, campaign, task_id, expected):
    _campaign(conn, org, brand, campaign, mutable=True)
    task = open_task(conn, org, brand, campaign, task_id)
    if type(expected) is not int or expected != task["revision"]:
        raise ValueError("素材任務已更新，請重新讀取後再操作。")
    row = conn.execute(
        "SELECT spec_json FROM ads_material_revision WHERE task_id=%s AND revision=%s"
        " AND org_id=%s AND brand_id=%s AND campaign_id=%s",
        (task_id, expected, org, brand, campaign),
    ).fetchone()
    return task, dict(row["spec_json"])


def _edit(conn, org, brand, spec, payload):
    if "title" in payload:
        spec["title"] = _text(payload["title"], 200, required=True)
    if "instruction" in payload:
        spec["instruction"] = _text(payload["instruction"], 8000)
    if "prompt" in payload:
        spec["prompt"] = _prompt(conn, org, brand, payload["prompt"])
        if spec["prompt"].get("part") == "copy" and "copy_fields" not in payload:
            spec["copy_fields"] = spec["prompt"]["copy_fields"]
    if "copy_fields" in payload:
        spec["copy_fields"] = assets.validate_copy(payload["copy_fields"])
        if (
            spec["prompt"].get("source") == "workbench"
            and spec["prompt"].get("part") == "copy"
            and spec["copy_fields"] != spec["prompt"]["copy_fields"]
        ):
            raise ValueError("文案已不同於工作檯原版本，請改為手動來源並保留原版本說明。")
    if "reference_asset_ids" in payload:
        spec["reference_asset_ids"] = _references(conn, org, brand, payload["reference_asset_ids"])
    spec.update(selected_candidate_id=None, placement_id=None, placement_revision=None)


def mutate(conn, org, brand, campaign, task_id, payload, action, actor):
    allowed = {
        "update": EDITABLE,
        "candidates": {"asset_ids", "prompt", "reference_asset_ids"},
        "select": {"candidate_id", "content_hash"},
    }
    if action not in allowed or set(payload) - allowed[action] - {
        "operation_id",
        "expected_revision",
    }:
        raise ValueError("素材操作欄位無效。")
    with _locked(conn, org, brand):
        operation, digest, prior = _prior(conn, org, brand, campaign, payload, action, task_id)
        if prior:
            return get(conn, org, brand, campaign, task_id, prior["result_revision"])
        task, spec = _base(conn, org, brand, campaign, task_id, payload.get("expected_revision"))
        if action == "update":
            _edit(conn, org, brand, spec, payload)
        elif action == "candidates":
            ids = payload.get("asset_ids")
            if (
                not isinstance(ids, list)
                or not 1 <= len(ids) <= 10
                or any(not isinstance(aid, str) for aid in ids)
            ):
                raise ValueError("每批請選擇一至十個已保存的候選原檔。")
            if len(set(ids)) != len(ids):
                raise ValueError("同批候選原檔不可重複。")
            if len(spec["candidates"]) + len(ids) > 100:
                raise ValueError("本任務已收一百個候選，請另建任務保留獨立上下文。")
            # Omitted provenance stays unknown, even if the task has a default prompt.
            prompt = _prompt(conn, org, brand, payload.get("prompt", {"source": "none"}))
            refs = _references(conn, org, brand, payload.get("reference_asset_ids", []))
            for aid in ids:
                asset = assets.get_asset(conn, org, brand, aid)
                if spec["mode"] in {"external_image", "workbench_image"} and not asset[
                    "mime_type"
                ].startswith("image/"):
                    raise ValueError("外部成圖候選需為圖片原檔。")
                spec["candidates"].append(
                    {
                        "id": db.new_id("amc"),
                        "asset_id": aid,
                        "filename": asset["filename"],
                        "mime_type": asset["mime_type"],
                        "sha256": asset["sha256"],
                        "prompt": prompt,
                        "reference_asset_ids": refs,
                        "batch_operation_id": operation,
                        "recorded_at": db.now_iso(),
                    }
                )
        else:
            if payload.get("content_hash") != task["content_hash"]:
                raise ValueError("選定內容已改變，請重新檢視。")
            candidate = next(
                (c for c in spec["candidates"] if c["id"] == payload.get("candidate_id")), None
            )
            if not candidate:
                raise ValueError("找不到此任務的候選版本。")
            placement = assets.attach(
                conn, org, brand, campaign, candidate["asset_id"], spec["copy_fields"], actor
            )
            spec.update(
                selected_candidate_id=candidate["id"],
                placement_id=placement["id"],
                placement_revision=placement["revision"],
            )
        revision = task["revision"] + 1
        generation_fields = {
            "mode",
            "instruction",
            "prompt",
            "reference_asset_ids",
            "review_context",
        }
        same_request = all(spec.get(k) == task.get(k) for k in generation_fields)
        if task["pack_id"] and spec["prompt"].get("pack_id") == task["pack_id"]:
            # Adopting this request's generated version records its result, not a new request.
            same_request = all(spec.get(k) == task.get(k) for k in generation_fields - {"prompt"})
        _write(
            conn,
            org,
            brand,
            campaign,
            task_id,
            revision,
            spec,
            inherit=task if same_request else None,
        )
        _remember(conn, org, brand, campaign, operation, digest, task_id, revision)
        conn.commit()
        return get(conn, org, brand, campaign, task_id)


def _retryable(task) -> bool:
    """F49 Contract T: the hand-off was prepared (a pack exists) but its enqueue is not known to
    have happened -- `dispatch` starts that same pack again, never a second pack."""
    return task["dispatch_status"] == "unknown" and bool(task["pack_id"])


def _start(conn, org, brand, task_id, revision, pack_id) -> None:
    """Enqueue the pack's generation; the revision reads `queued` once that went through. A failed
    enqueue leaves it `unknown` (交棒沒送出・可重試) -- the next `dispatch` retries this pack."""
    try:
        workbench.start_material_pack(conn, org, brand, pack_id)
    except Exception:
        conn.rollback()
        logger.exception("starting material pack %s failed", pack_id)
        return
    conn.execute(
        "UPDATE ads_material_revision SET dispatch_status='queued'"
        " WHERE task_id=%s AND revision=%s AND pack_id=%s",
        (task_id, revision, pack_id),
    )
    conn.commit()


def dispatch(conn, org, brand, campaign, task_id, payload, actor):
    """Hand the revision to the workbench once (a pack, then its enqueue). F49 Contract T: a
    revision left `unknown` with a pack (the enqueue failed) is retried on that same pack by the
    next dispatch -- a replay of the same operation included."""
    if set(payload) != {"operation_id", "expected_revision", "content_hash"}:
        raise ValueError("請核對本版內容後再交棒。")
    with _locked(conn, org, brand):
        operation, digest, prior = _prior(conn, org, brand, campaign, payload, "dispatch", task_id)
        if prior:
            done = get(conn, org, brand, campaign, task_id, prior["result_revision"])
            if _retryable(done) and done["cancelled_at"] is None \
                    and done["revision"] == done["current_revision"]:
                _campaign(conn, org, brand, campaign, mutable=True)
                _start(conn, org, brand, task_id, done["revision"], done["pack_id"])
                return get(conn, org, brand, campaign, task_id, prior["result_revision"])
            return done
        task, spec = _base(conn, org, brand, campaign, task_id, payload.get("expected_revision"))
        if task["mode"] not in {"workbench_image", "copy"}:
            raise ValueError("已有成品或自行提供提示詞不需要派工生成。")
        if payload["content_hash"] != task["content_hash"]:
            raise ValueError("任務內容已變，請重新檢視後再交棒。")
        if _retryable(task):
            _remember(conn, org, brand, campaign, operation, digest, task_id, task["revision"])
            conn.commit()
            _start(conn, org, brand, task_id, task["revision"], task["pack_id"])
            return get(conn, org, brand, campaign, task_id)
        if task["dispatch_status"] != "not_requested":
            # Another operation ID cannot create a second generation for the same content.
            _remember(conn, org, brand, campaign, operation, digest, task_id, task["revision"])
            conn.commit()
            return task
        part = "copy" if task["mode"] == "copy" else "image_prompt"
        context = spec.get("review_context") or {}
        instruction = spec["instruction"]
        if context:
            instruction += "\n上一回待驗假設（不是已確認事實）：" + context["hypothesis"]
            instruction += "\n建議下一步：" + context["next_step"]
            instruction += "\n資料限制：" + "；".join(context["limitations"] + context["risks"])
            instruction += "\n上一回引用證據（保留來源與限制）：" + json.dumps(
                context["sources"], ensure_ascii=False
            )
        if spec["prompt"].get("text"):
            instruction += "\n使用者選定的前版文字：" + spec["prompt"]["text"]
        if spec["reference_asset_ids"]:
            names = [
                assets.get_asset(conn, org, brand, aid)["filename"]
                for aid in spec["reference_asset_ids"]
            ]
            instruction += "\n已保存參考圖原檔（僅檔名，未傳入圖片或分析內容）：" + "、".join(names)
        source = {
            "material_task_id": task_id,
            "material_revision": task["revision"],
            "campaign_id": campaign,
            "review_id": spec["review_id"],
            "recommendation_id": spec["recommendation_id"],
        }
        pack_id = workbench.prepare_material_pack(
            conn,
            org,
            brand,
            {
                "source_ref": source,
                "name": spec["title"],
                "context": {
                    "origin_label": "投放中心 → " + spec["title"],
                    "origin_href": (
                        f"/brands/{brand}/ads/campaigns/{campaign}?tab=assets&material={task_id}"
                    ),
                },
                "summary": {"情境": instruction},
                "sets": [
                    {
                        "name": spec["title"],
                        "required_outputs": {part: 1},
                        "request": {
                            "free_text": instruction,
                            "copy_length": "short",
                            "use_brand_knowledge": True,
                        },
                    }
                ],
            },
        )
        conn.execute(
            "UPDATE ads_material_revision SET pack_id=%s,dispatch_status='unknown',approved_hash=%s"
            " WHERE task_id=%s AND revision=%s",
            (pack_id, task["content_hash"], task_id, task["revision"]),
        )
        _remember(conn, org, brand, campaign, operation, digest, task_id, task["revision"])
        # Durable before enqueue: interrupted calls must not blindly send a model twice.
        conn.commit()
        _start(conn, org, brand, task_id, task["revision"], pack_id)
        return get(conn, org, brand, campaign, task_id)


class InUse(ValueError):
    """An approved change set already references this request; it can no longer be cancelled."""


def cancel(conn, org, brand, campaign, task_id, actor):
    """Withdraw a request. The task and its revisions stay readable (a workbench pack keeps its
    origin link); it only leaves the list and frees its "replace this ad" slot."""
    _campaign(conn, org, brand, campaign, mutable=True)
    with _locked(conn, org, brand):
        # Row lock first: approval reads the task FOR SHARE, so it cannot slip in between the
        # in-use check and the cancel.
        row = conn.execute(
            "SELECT cancelled_at FROM ads_material_task WHERE org_id=%s AND brand_id=%s"
            " AND campaign_id=%s AND id=%s FOR UPDATE",
            (org, brand, campaign, task_id),
        ).fetchone()
        if not row:
            raise ValueError("找不到此品牌活動的素材任務或版本。")
        if row["cancelled_at"] is None:
            if conn.execute(
                "SELECT 1 FROM ads_change_set WHERE org_id=%s AND brand_id=%s AND campaign_id=%s"
                " AND status='approved' AND plan_json->>'material_task_id'=%s LIMIT 1",
                (org, brand, campaign, task_id),
            ).fetchone():
                raise InUse("此素材需求已被核准的變更清單採用，不能取消。")
            conn.execute(
                "UPDATE ads_material_task SET cancelled_at=now(),cancelled_by=%s"
                " WHERE org_id=%s AND brand_id=%s AND campaign_id=%s AND id=%s",
                (actor, org, brand, campaign, task_id),
            )
        conn.commit()
        return get(conn, org, brand, campaign, task_id)
