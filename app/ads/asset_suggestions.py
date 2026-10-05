"""Durable single-call suggestions and explicit revision confirmation, owned by ads."""

import hashlib
import math

from app import background, workbench
from app.ads import asset_suggestion_policy as policy
from app.ads import live_creative, sell_way, targets
from app.ads import repository as campaigns
from app.ads import user_assets_repository as assets
from app.core import db, settings
from app.llm import context_compiler, gateway, providers

TASK_TYPE = "ads_user_asset_suggestions"
TASK = "background.ads_user_asset_suggestions"
PROVIDER = providers.AnthropicProvider()
PROMPT = db.APP_DIR / "departments" / "ads" / "user_asset_suggestions.md"


def get_batch(conn, org, brand, campaign, batch_id):
    if not isinstance(batch_id, str) or not 1 <= len(batch_id) <= 200:
        raise ValueError("建議批次識別碼無效。")
    row = conn.execute(
        "SELECT * FROM ads_asset_suggestion_batch WHERE org_id=%s AND brand_id=%s AND "
        "campaign_id=%s AND id=%s",
        (org, brand, campaign, batch_id),
    ).fetchone()
    if row is None:
        raise ValueError("找不到建議批次。")
    result = dict(row)
    ids = [p["id"] for p in result["input_json"]["placements"]]
    result["remaining_count"] = conn.execute(
        "SELECT COUNT(*) AS n FROM ads_asset_placement WHERE org_id=%s AND brand_id=%s "
        "AND campaign_id=%s AND is_current AND confirmed_at IS NULL AND NOT(id=ANY(%s))",
        (org, brand, campaign, ids),
    ).fetchone()["n"]
    result["usage_notice"] = (
        policy.CODEX_NOTICE
        if result["input_json"]["provider"] == "codex_cli"
        else "每次生成最多 US$0.50 預留；與全站其他功能的並行預留未共用鎖。"
    )
    result["retry_notice"] = "失敗批次不自動重送；可先手動修訂文案與安排。"
    result["stale"] = False
    if result["status"] == "succeeded":
        try:
            result["stale"] = (
                fingerprint(_current_snapshot(conn, org, brand, campaign, result))
                != result["input_hash"]
            )
        except ValueError:
            result["stale"] = True
    return result


def _judged_against(conn, org, brand, campaign, ad_id):
    """F44: what a placement's copy is judged against -- the sell-way and the offer coordinate
    of the planned ad it was uploaded for, the same two the copy step wrote it from. A library
    placement (no ad) has the campaign's sell-way and no offer coordinate.
    F48 Contract G: the offer is the one the ad's copy was written for (`live_creative.offer_for`:
    the dispatched set's snapshot, else the ad's current key) -- the slots read the same."""
    ad = campaigns.get_ad(conn, org, brand, ad_id) if ad_id else None
    if ad is None:
        return {"sell_way": sell_way.of_campaign(campaign), "offer_key": None, "offer_label": None}
    offer_key = live_creative.offer_for(conn, org, brand, campaign["id"], ad)
    label = None
    if offer_key:
        # The label the plan showed. The snapshot is taken at plan time and the coordinate
        # stays editable, so a snapshot of another key falls back to the brand's vocabulary.
        planned = (ad.get("coordinates_snapshot_json") or {}).get("offer")
        if isinstance(planned, dict) and planned.get("key") == offer_key:
            label = planned.get("label")
        if not label:
            label = next(
                (
                    row["label"]
                    for row in campaigns.coordinate_vocabulary(conn, org, brand)
                    if row["dimension"] == "offer" and row["key"] == offer_key
                ),
                offer_key,
            )
    return {
        "sell_way": sell_way.of_ad(ad, campaign),
        "offer_key": offer_key,
        "offer_label": label,
    }


def snapshot(conn, org, brand, campaign_id, requested, summary):
    campaign = campaigns.get_campaign(conn, org, brand, campaign_id)
    if campaign is None or campaign["status"] == "closed":
        raise ValueError("活動不存在或已結案，只能查看歷史。")
    if not isinstance(requested, list) or not 1 <= len(requested) <= 10:
        raise ValueError("每批請選 1 至 10 件素材，其餘保留待處理。")
    if not isinstance(summary, str) or len(summary) > 2000:
        raise ValueError("整批說明最多 2,000 字元。")
    placements = []
    for item in requested:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("id"), str)
            or isinstance(item.get("revision"), bool)
            or not isinstance(item.get("revision"), int)
        ):
            raise ValueError("請提供素材 ID 與正確版本。")
        row = assets.placement(conn, org, brand, campaign_id, item["id"])
        if row["revision"] != item["revision"]:
            raise ValueError("素材安排已更新，請重新載入。")
        original = assets.get_asset(conn, org, brand, row["asset_id"])
        placements.append(
            {
                k: row[k]
                for k in (
                    "id",
                    "revision",
                    "asset_id",
                    "ad_id",
                    "copy_fields",
                    "required",
                    "purpose",
                    "destination_entity_id",
                    "start_date",
                    "end_date",
                )
            }
            | {
                "media_status": original["status"],
                "media_error": original["error"],
                "mime_type": original["mime_type"],
            }
            | _judged_against(conn, org, brand, campaign, row["ad_id"])
        )
    if len({p["id"] for p in placements}) != len(placements):
        raise ValueError("本批素材不能重複。")
    placements.sort(key=lambda p: p["id"])
    campaign["budget_total"] = (campaigns.campaign_detail(conn, org, brand, campaign_id) or {}).get(
        "budget_total"
    )
    text, knowledge, version, _ = context_compiler.compile(conn, brand, include_personas=False)
    campaign_sell_way = sell_way.of_campaign(campaign)
    sources = policy.source_rows(conn, brand, knowledge, campaign_sell_way)
    # F48 Contract G: the model is told the same 「不能講」 list the confirmation blocks on.
    forbidden = workbench.forbidden_terms(conn, org, brand, campaign_sell_way)
    # The sell-way's own claims are sources the brand-level compile did not list.
    knowledge = list(dict.fromkeys([*knowledge, *(s["id"] for s in sources)]))
    native = conn.execute(
        "SELECT id,native_kind,native_id,source_account,currency,budget_amount,budget_type,"
        "start_date,end_date,parent_native_id FROM ads_external_entity WHERE org_id=%s AND "
        "brand_id=%s AND campaign_id=%s ORDER BY id LIMIT 101",
        (org, brand, campaign_id),
    ).fetchall()
    return {
        "placements": placements,
        "requested": [{"id": p["id"], "revision": p["revision"]} for p in placements],
        "summary": summary,
        "brand_version": version,
        "knowledge_ids": knowledge,
        "context": text,
        "sources": sources,
        "forbidden": forbidden,
        "campaign": {
            k: campaign[k]
            for k in (
                "id",
                "name",
                "goal_text",
                "objective",
                "budget_total",
                "start_date",
                "end_date",
                "updated_at",
            )
        }
        # F28-I01: the one cap (cost per result), resolved like every other reader.
        | {"cap": targets.resolve(conn, org, brand, campaign)["value"]}
        | {"sell_way": campaign_sell_way},
        "native": [dict(n) for n in native],
        "native_overflow": len(native) > 100,
    }


def fingerprint(value):
    return hashlib.sha256(policy.encode(value).encode()).hexdigest()


def _reserve(conn, org, brand, batch_id, amount):
    # All F13 reservations share this short transaction lock; other features do not.
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("ads-suggestion-budget:" + org,)
    )
    since = settings.org_month_start(conn, org_id=org)  # F50 Contract K: the org's month
    spent = settings.org_ai_spent_this_month(conn, org_id=org, since=since)
    extra = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN settlement='held' THEN amount ELSE 0 END),"
        "0)+COALESCE(SUM(CASE WHEN created_at>=%s THEN known_failed_cost ELSE 0 END),0) AS "
        "n FROM ads_asset_suggestion_reservation WHERE org_id=%s",
        (since, org),
    ).fetchone()["n"]
    limit = settings.get_ai_monthly_cost_limit(conn, org_id=org)
    if amount and (not math.isfinite(limit) or spent + float(extra) + amount > limit):
        raise ValueError("組織剩餘 AI 額度不足以預留本批費用，未送出。")
    conn.execute(
        "INSERT INTO ads_asset_suggestion_reservation(batch_id,org_id,brand_id,amount) "
        "VALUES(%s,%s,%s,%s)",
        (batch_id, org, brand, amount),
    )


def request(conn, org, brand, campaign, requested, key, summary=""):
    if not isinstance(key, str) or not 1 <= len(key) <= 200:
        raise ValueError("請提供批次識別碼。")
    data = snapshot(conn, org, brand, campaign, requested, summary)
    provider = providers.select_provider(PROVIDER, task_type=TASK_TYPE)
    model = providers.resolve_model(task_type=TASK_TYPE, conn=conn, brand_id=brand)
    data["provider"] = provider.name
    data["model"] = model
    system = PROMPT.read_text(encoding="utf-8")
    data["template_hash"] = fingerprint(system)
    digest = fingerprint(data)
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
        (f"ads-suggestion:{org}:{brand}:{campaign}",),
    )
    existing = conn.execute(
        "SELECT * FROM ads_asset_suggestion_batch WHERE org_id=%s AND brand_id=%s AND "
        "campaign_id=%s AND (input_hash=%s OR idempotency_key=%s)",
        (org, brand, campaign, digest, key),
    ).fetchone()
    if existing:
        if existing["input_hash"] != digest:
            raise ValueError("此批次識別碼已用於不同內容，請重新載入。")
        conn.commit()
        return get_batch(conn, org, brand, campaign, existing["id"])
    messages = _messages(data)
    framing = 32 if provider.name == "codex_cli" else 0
    brand_only = policy.encode(
        {
            "brand_context": data["context"],
            "sources": data["sources"],
            "forbidden": data["forbidden"],
        }
    )
    if len(system) + len(brand_only) + framing > policy.INPUT_CHARS:
        raise ValueError(
            "品牌規則與來源本身超過 12,000 字元，縮小批次也無法處理；請改用手動文案與安排確認。"
        )
    if len(system) + len(messages[0]["content"]) + framing > policy.INPUT_CHARS:
        raise ValueError(
            "批次與品牌規則合計超過 12,000 字元；請縮小批次或整理過長來源，原素材仍保留。"
        )
    amount = policy.ceiling(provider.name, model)
    batch_id = db.new_id("asb")
    conn.execute(
        "INSERT INTO ads_asset_suggestion_batch(id,org_id,brand_id,campaign_id,input_hash,"
        "idempotency_key,input_json) VALUES(%s,%s,%s,%s,%s,%s,%s)",
        (batch_id, org, brand, campaign, digest, key, db.jsonb(data)),
    )
    try:
        _reserve(conn, org, brand, batch_id, amount)
    except Exception:
        conn.rollback()
        raise
    conn.commit()  # The gateway commits internally; never hold a budget transaction during IO.
    enqueue(org, brand, campaign, batch_id)
    return get_batch(conn, org, brand, campaign, batch_id)


def _messages(data):
    return [
        {
            "role": "user",
            "content": policy.encode(
                {
                    "brand_context": data["context"],
                    "confirmed_sources": data["sources"],
                    "forbidden": data["forbidden"],
                    "campaign": data["campaign"],
                    "placements": data["placements"],
                    "unverified_user_summary": data["summary"],
                    "media_analysis": "not_analyzed",
                }
            ),
        }
    ]


def enqueue(org, brand, campaign, batch_id):
    if not background.is_active("asset-suggestion:" + batch_id):
        background.enqueue(
            TASK,
            org_id=org,
            lock="asset-suggestion:" + batch_id,
            brand_id=brand,
            campaign_id=campaign,
            batch_id=batch_id,
        )


def dispatch_pending(timestamp):
    with db.connection() as conn:
        conn.execute(
            "UPDATE ads_asset_suggestion_batch SET status='unknown',"
            "error='執行狀態不明，預留保留；不自動重送，可先手動修訂安排。',updated_at=now() "
            "WHERE status='running' AND updated_at<now()-interval '10 minutes'"
        )
        conn.commit()
        rows = conn.execute(
            "SELECT org_id,brand_id,campaign_id,id FROM ads_asset_suggestion_batch WHERE "
            "status='queued' ORDER BY created_at LIMIT 100"
        ).fetchall()
    for row in rows:
        enqueue(row["org_id"], row["brand_id"], row["campaign_id"], row["id"])


def _settle(conn, org, batch_id, task):
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("ads-suggestion-budget:" + org,)
    )
    cost = task.get("cost")
    if cost is not None:
        conn.execute(
            "UPDATE ads_asset_suggestion_reservation SET settlement='settled',"
            "known_failed_cost=%s WHERE org_id=%s AND batch_id=%s",
            (float(cost) if task["status"] != "succeeded" else 0, org, batch_id),
        )
    conn.commit()


def _result(conn, org, brand, data, item, answer):
    original = item["copy_fields"]
    additions = {
        k: v
        for k, v in answer["copy_fields"].items()
        if not str(original.get(k) or "").strip() and v.strip()
    }
    # F44: the copy is judged against the placement's sell-way and offer coordinate (the sources
    # the copy step used); every problem is a Contract C detail naming the exit that fixes it.
    judged = {k: item[k] for k in ("sell_way", "offer_key", "offer_label")}
    problems = policy.violations(
        conn, org, brand, original, data["sources"], generated=False, **judged
    )
    generated_errors = policy.violations(
        conn, org, brand, additions, data["sources"], generated=True, **judged
    )
    if generated_errors:
        additions = {}
        problems += generated_errors
    effective = {**additions, **{k: v for k, v in original.items() if str(v).strip()}}
    # F46 Contract O: judged on the whole copy that would be confirmed (the original plus any
    # accepted addition), so an offer sentence written in either half counts.
    offer_missing = policy.missing_offer(conn, org, brand, effective, **judged)
    if offer_missing is not None:
        problems.append(offer_missing)
    campaign = data["campaign"]
    if not campaign["goal_text"] or not campaign["objective"]:
        problems.append(policy.detail("campaign", "請補活動目標，才能確認此批用途。"))
    notes = []
    statutory = policy.statutory_note(conn, org, brand, effective, item["sell_way"])
    if statutory is not None:
        notes.append(statutory)
    if campaign["cap"] is None:
        notes.append("上限待補，不保證曝光或花費。")
    if item["media_status"] != "ready":
        if item["media_error"]:
            problems.append(policy.detail("file", item["media_error"]))
        else:
            problems.append(policy.detail("wait", "原檔預覽尚未完成，請先完成媒體處理。"))
    if any(not str(effective.get(k) or "").strip() for k in policy.FIELDS):
        problems.append(policy.detail("copy", "請補齊標題、內文與說明，或補充可用品牌事實。"))
    roots = [n for n in data["native"] if n["parent_native_id"] is None]
    root = roots[0] if len(roots) == 1 and not data["native_overflow"] else {}
    start = item["start_date"] or campaign["start_date"] or root.get("start_date")
    end = item["end_date"] or campaign["end_date"] or root.get("end_date")
    if start and end and str(end) < str(start):
        problems.append(policy.detail("campaign", "內部安排日期範圍不一致，請核對起訖日期。"))
    if not start or not end:
        notes.append("平台或內部起訖日期不完整，手動上架時請核對。")
    budget = campaign["budget_total"]
    if budget is None and root.get("currency") and root.get("budget_type") in {"daily", "lifetime"}:
        budget = root.get("budget_amount")
    if budget is None:
        notes.append("預算尚未確認；不混算不同層級／幣別，不保證曝光或花費。")
    elif float(budget) <= 0:
        problems.append(
            policy.detail(
                "campaign",
                "目前已知預算為零，本件保留必用待安排；請先核對手動上架計畫，不會修改平台預算。",
            )
        )
    destination = item["destination_entity_id"]
    if destination is None:
        roots = [n for n in data["native"] if n["parent_native_id"] is None]
        if len(roots) == 1 and not data["native_overflow"]:
            destination = roots[0]["id"]
    purpose = item["purpose"] or answer["purpose"]
    if not item["purpose"]:
        allowed_purposes = {
            "認識品牌",
            "介紹品牌",
            "產品介紹",
            "商品資訊",
            "品牌介紹",
            "活動介紹",
            "導流",
        }
        if purpose not in allowed_purposes:
            purpose = ""
    if not purpose.strip():
        problems.append(policy.detail("campaign", "請補這件素材的投放用途。"))
    details: dict = {}  # one detail per sentence, first seen first
    for problem in problems:
        details.setdefault(problem["text"], problem)
    return {
        "id": item["id"],
        "revision": item["revision"],
        "original_copy": original,
        "suggested_copy": additions,
        "effective_copy": effective,
        "purpose": purpose,
        "destination_entity_id": destination,
        "start_date": start,
        "end_date": end,
        "required": item["required"],
        "unknowns": ["media_not_analyzed", "user_summary_unverified"],
        "notes": notes,
        # `pending_reasons` stays the sentences alone (the AI-batch screen reads it).
        "pending_reasons": list(details),
        "pending_details": list(details.values()),
        "status": "pending" if problems else "awaiting_confirmation",
    }


def run(org_id, brand_id, campaign_id, batch_id):
    with db.connection() as conn:
        db.set_tenant_scope(conn, org_id)
        batch = get_batch(conn, org_id, brand_id, campaign_id, batch_id)
        changed = conn.execute(
            "UPDATE ads_asset_suggestion_batch SET status='running',updated_at=now() WHERE "
            "id=%s AND status='queued'",
            (batch_id,),
        ).rowcount
        conn.commit()
        if not changed:
            return
        data = batch["input_json"]
        try:
            current = snapshot(
                conn, org_id, brand_id, campaign_id, data["requested"], data["summary"]
            )
            for key in ("provider", "model", "template_hash"):
                current[key] = data[key]
            if fingerprint(current) != batch["input_hash"]:
                raise ValueError("資料已改變，本批未送出，請重新建立建議。")
            actual = providers.select_provider(PROVIDER, task_type=TASK_TYPE)
            model = providers.resolve_model(task_type=TASK_TYPE, conn=conn, brand_id=brand_id)
            if actual.name != data["provider"] or model != data["model"]:
                raise ValueError("模型設定已改變，本批未送出，請重新建立建議。")
            system = PROMPT.read_text(encoding="utf-8")
            if fingerprint(system) != data["template_hash"]:
                raise ValueError("生成規則已改變，本批未送出，請重新建立建議。")
        except ValueError as exc:
            conn.rollback()
            _settle(conn, org_id, batch_id, {"cost": 0, "status": "failed"})
            conn.execute(
                "UPDATE ads_asset_suggestion_batch SET status='failed',error=%s WHERE id=%s",
                (str(exc), batch_id),
            )
            conn.commit()
            return
        try:
            task = gateway.run_task(
                conn,
                PROVIDER,
                brand_id=brand_id,
                task_type=TASK_TYPE,
                prompt_template_id="ads/user_asset_suggestions",
                prompt_template_version=data["template_hash"],
                system=system,
                messages=_messages(data),
                context=gateway.TaskContext(
                    context_scope={"brand_id": brand_id, "suggestion_batch_id": batch_id},
                    knowledge_item_ids=data["knowledge_ids"],
                    brand_version=data["brand_version"],
                ),
                options=gateway.TaskOptions(
                    model=model,
                    max_tokens=policy.OUTPUT_TOKENS,
                    timeout_s=policy.TIMEOUT_SECONDS,
                    max_retries=0,
                ),
            )
            _settle(conn, org_id, batch_id, task)
            conn.execute(
                "UPDATE ads_asset_suggestion_batch SET llm_task_id=%s WHERE id=%s",
                (task["id"], batch_id),
            )
            conn.commit()
            if task["status"] != "succeeded":
                raise ValueError("生成未完成，費用不明時保留預留，不自動重送。")
            if len(task.get("rendered_output") or "") > policy.OUTPUT_CHARS:
                raise ValueError("回傳超過 16,384 字元接受上限，未採用；這不是生成用量硬上限。")
            parsed = gateway.parse_json_reply(task.get("rendered_output") or "")
            answers = policy.validate_reply(parsed, data["placements"])
            results = [
                _result(conn, org_id, brand_id, data, item, answers[item["id"]])
                for item in data["placements"]
            ]
            conn.execute(
                "UPDATE ads_asset_suggestion_batch SET status='succeeded',results=%s,"
                "error=NULL,updated_at=now() WHERE id=%s",
                (db.jsonb(results), batch_id),
            )
            conn.commit()
        except Exception as exc:
            conn.rollback()
            reason = str(exc) if isinstance(exc, ValueError) else "生成中斷，預留保留、不自動重送。"
            conn.execute(
                "UPDATE ads_asset_suggestion_batch SET status='failed',error=%s,"
                "updated_at=now() WHERE id=%s",
                (reason, batch_id),
            )
            conn.commit()


def confirm(conn, org, brand, campaign, placement_id, expected_revision, batch_id, actor):
    if (
        isinstance(expected_revision, bool)
        or not isinstance(expected_revision, int)
        or expected_revision < 1
    ):
        raise ValueError("請提供正整數版本。")
    if batch_id is None:
        return confirm_manual(conn, org, brand, campaign, placement_id, expected_revision, actor)
    batch = get_batch(conn, org, brand, campaign, batch_id)
    if batch["status"] != "succeeded":
        raise ValueError(batch["error"] or "建議尚未完成。")
    conn.execute(
        "SELECT id FROM ads_asset_placement WHERE org_id=%s AND brand_id=%s AND "
        "campaign_id=%s AND id=%s AND is_current FOR UPDATE",
        (org, brand, campaign, placement_id),
    )
    old = assets.placement(conn, org, brand, campaign, placement_id)
    if old["revision"] != expected_revision:
        raise ValueError("素材版本已更新，請重新載入。")
    if old["confirmed_at"]:
        if old["suggestion_batch_id"] == batch_id:
            return old
        raise ValueError("此版本已有確認，請先明確修訂再確認新建議。")
    current = _current_snapshot(conn, org, brand, campaign, batch)
    if fingerprint(current) != batch["input_hash"]:
        raise ValueError("品牌／活動／素材資料已改變，請重新取得建議。")
    result = next(
        (
            r
            for r in batch["results"]
            if r["id"] == placement_id and r["revision"] == expected_revision
        ),
        None,
    )
    if result is None:
        raise ValueError("此版本不在指定建議批次。")
    if result["pending_reasons"]:
        return _refused(conn, org, brand, campaign, old, result)
    return _apply_confirmation(
        conn,
        org,
        brand,
        campaign,
        placement_id,
        expected_revision,
        result,
        batch_id,
        batch["input_hash"],
        actor,
    )


def store_refusal(
    conn, org, brand, campaign, placement_id, revision, details, *, assignment=False
) -> list:
    """§6.49: the one writer of a refusal. A refused confirmation keeps its non-`wait` Contract C
    details on that revision (`blocked_reasons`) -- every path that confirms (manual, batch,
    slot upload, copy pick, copy edit, recheck) ends here, so a refusal is never only a response.
    `wait` details (the preview is not made yet) are not a refusal of the copy and are dropped;
    the stored list replaces the previous one (the newest refusal is the fact). A confirmed
    revision is never touched; `_apply_confirmation` clears the list.
    F49 Contract T: `assignment=True` is the one exception -- why `handoff_assignment.assign`
    refused a confirmed revision (details of kind `assign`, with their `code`; `[]` clears them
    once an assignment goes through), written on that confirmed revision only."""
    kept = [d for d in details if d["kind"] != "wait"]
    if assignment and any(d["kind"] != "assign" for d in kept):
        raise TypeError("assignment refusals are kind `assign` only")
    conn.execute(
        "UPDATE ads_asset_placement SET blocked_reasons=%s WHERE org_id=%s AND brand_id=%s "
        "AND campaign_id=%s AND id=%s AND revision=%s AND (confirmed_at IS NULL) <> %s",
        (db.jsonb(kept), org, brand, campaign, placement_id, revision, assignment),
    )
    conn.commit()
    return kept


def _refused(conn, org, brand, campaign, old, result):
    """A refused confirmation: stored on the revision (`store_refusal`), then returned as the
    unconfirmed placement plus why (sentences and Contract C details, same order)."""
    kept = store_refusal(
        conn, org, brand, campaign, old["id"], old["revision"], result["pending_details"]
    )
    return {
        **old,
        "blocked_reasons": kept,
        "status": "pending",
        "pending_reasons": result["pending_reasons"],
        "pending_details": result["pending_details"],
    }


def _current_snapshot(conn, org, brand, campaign, batch):
    data = batch["input_json"]
    batch_id = batch["id"]
    current = snapshot(conn, org, brand, campaign, data["requested"], data["summary"])
    # Confirming another member of this batch updates its proposed arrangement only.
    # Its immutable original revision and copy remain the original generation inputs.
    previous = {p["id"]: p for p in data["placements"]}
    for entry in current["placements"]:
        row = assets.placement(conn, org, brand, campaign, entry["id"])
        if row["confirmed_at"] and row["suggestion_batch_id"] == batch_id:
            for key in ("purpose", "destination_entity_id", "start_date", "end_date"):
                entry[key] = previous[entry["id"]][key]
    for key in ("provider", "model", "template_hash"):
        current[key] = data[key]
    return current


def _apply_confirmation(
    conn, org, brand, campaign, placement_id, expected_revision, result, batch_id, digest, actor
):
    # Confirmation records internal intent only; no native campaign or brand fact is changed.
    conn.execute(
        "UPDATE ads_asset_placement SET suggested_copy=%s,purpose=%s,"
        "destination_entity_id=%s,start_date=%s,end_date=%s,status='manual_ready',"
        "pending_reason='',blocked_reasons='[]'::jsonb,confirmed_by=%s,confirmed_at=now(),"
        "suggestion_batch_id=%s,"
        "suggestion_input_hash=%s WHERE org_id=%s AND brand_id=%s AND campaign_id=%s AND "
        "id=%s AND revision=%s AND confirmed_at IS NULL",
        (
            db.jsonb(result["suggested_copy"]),
            result["purpose"],
            result["destination_entity_id"],
            result["start_date"],
            result["end_date"],
            actor,
            batch_id,
            digest,
            org,
            brand,
            campaign,
            placement_id,
            expected_revision,
        ),
    )
    return assets.placement(conn, org, brand, campaign, placement_id)


def confirm_manual(conn, org, brand, campaign, placement_id, expected_revision, actor):
    conn.execute(
        "SELECT id FROM ads_asset_placement WHERE org_id=%s AND brand_id=%s AND "
        "campaign_id=%s AND id=%s AND is_current FOR UPDATE",
        (org, brand, campaign, placement_id),
    )
    old = assets.placement(conn, org, brand, campaign, placement_id)
    if old["revision"] != expected_revision:
        raise ValueError("素材版本已更新，請重新載入。")
    if old["confirmed_at"]:
        return old
    data = snapshot(
        conn, org, brand, campaign, [{"id": placement_id, "revision": expected_revision}], ""
    )
    result = _result(
        conn, org, brand, data, data["placements"][0], {"copy_fields": {}, "purpose": ""}
    )
    if result["pending_reasons"]:
        return _refused(conn, org, brand, campaign, old, result)
    return _apply_confirmation(
        conn,
        org,
        brand,
        campaign,
        placement_id,
        expected_revision,
        result,
        None,
        fingerprint(data),
        actor,
    )


def list_batches(conn, org, brand, campaign, *, after=None, limit=20):
    if campaigns.get_campaign(conn, org, brand, campaign) is None:
        raise ValueError("找不到活動。")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ValueError("每頁請選 1 至 50 筆。")
    rows = conn.execute(
        "SELECT id,status,error,created_at,updated_at FROM ads_asset_suggestion_batch "
        "WHERE org_id=%s AND brand_id=%s AND campaign_id=%s AND (%s::text IS NULL OR "
        "id<%s) ORDER BY id DESC LIMIT %s",
        (org, brand, campaign, after, after, limit + 1),
    ).fetchall()
    return {
        "batches": [dict(row) for row in rows[:limit]],
        "next_cursor": rows[limit - 1]["id"] if len(rows) > limit else None,
    }
