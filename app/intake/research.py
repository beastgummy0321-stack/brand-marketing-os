"""app/intake/research.py — 建檔精靈第 5 步「品牌知識」：系統自己跑的調研（F05-I09）。

因果鏈：`create_items` 全專案只有 `state.py:284` 一個呼叫端，資料來源是貼回那一步——
外部 AI 的貼回原本是 `brand_fact`／`product_fact` 的唯一寫入者。這裡不新增第二個
寫入者、也不新增第二個解析器：系統跑出來的文字一樣餵給 `state.apply_paste`，
走 `paste_parse` → `create_items` 那條唯一的路。

自己的 `APIRouter`，在 `routes_api.py` 檔尾併入——不 import `routes_api`，避免循環
（`routes_api.py` import 這個檔案，方向是單向的）。

這一輪不開網路搜尋（feature Decisions 第 14 條，使用者可翻案）：`gateway.TaskOptions.tools`
維持 `None`。系統自己跑沒有網路搜尋能力，只能讀使用者自己填的網址（`app.core.net.fetch_url`）
與品牌自己已有的資料，提示詞明文禁止編造來源、這一輪也不產「顧客原話」。
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Request

from app.background import JOB_FAILED_MESSAGE
from app.background import enqueue as background_enqueue
from app.background import is_active as background_is_active
from app.background import job_outcome as background_job_outcome
from app.brand_intelligence import background_job
from app.brand_intelligence import repository as bi_repo
from app.core import net
from app.core.db import connection as core_db_connection
from app.core.db import new_id, now_iso
from app.intake import ai, script, state
from app.intake import repository as ir
from app.llm import gateway
from app.shared import web
from app.shared.web import require_actor, require_brand

router = APIRouter()

# 測試可整個換掉（跟 app/intake/ai.py 同風格）——呼叫 LLM 走 `ai._run`（既有的建檔精靈
# 呼叫入口，讀 `brand.knowledge_version` 那句 SQL 已經記在 KNOWN_SQL_VIOLATIONS 裡，
# 不在這裡重開第二處）；`net.fetch_url` 讀網址自己留一份可換的別名，跟 provider 是否
# 被測試換掉無關。
TASK_TYPE = "intake_research"
fetch_url = net.fetch_url
_USUAL_RANGE_TEXT = "1 到 3 分鐘"

_SYSTEM = (
    "你是資深品牌顧問，正在替品牌方整理品牌知識，供之後的廣告與品牌內容生成直接使用。"
    "你沒有網路，只能用使用者提供的材料工作，不得自己上網查、不得編造任何來源或內容；"
    "查不出來的就不要寫，寧可少幾條。"
)


def _envelope(data) -> dict:
    return {"data": data, "generated_at": datetime.now(UTC).isoformat()}


async def _json_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _lock(brand_id: str) -> str:
    return f"intake_research:{brand_id}"


# ---------------------------------------------------------------------------
# 提示詞（就地組，不照抄 script.build_prompt——那份是寫給能上網的外部 AI 用的）
# ---------------------------------------------------------------------------

def _impressions_text(draft: dict) -> str:
    imps = draft.get("scan_impressions") or []
    if not imps:
        return "（沒有初掃印象。）"
    return "\n".join(f"- （看起來像{i['looks_like']}）{i['title']}：{i['content']}" for i in imps)


def _qa_text(draft: dict) -> str:
    answers = draft.get("answers") or []
    if not answers:
        return "（沒有回答額外問題。）"
    lines = []
    for a in answers:
        line = f"- {a['question']}\n  回答：{a['choice_label']}"
        if a.get("note"):
            line += f"（補充：{a['note']}）"
        lines.append(line)
    return "\n".join(lines)


def _url_excerpts(draft: dict) -> tuple:
    excerpts, missing = [], []
    for u in draft.get("urls") or []:
        ok, text = fetch_url(u)
        if ok and text:
            excerpts.append(f"【{u}】\n{text}")
        else:
            missing.append(u)
    return excerpts, missing


def build_prompt(conn, draft: dict, existing: dict) -> str:
    known = sorted(p["name"] for p in bi_repo.list_products(conn, draft["brand_id"]))
    excerpts, missing_urls = _url_excerpts(draft)
    confirmed = script.confirmed_data_block(existing)

    parts = [
        f"【品牌】{draft['brand_name']}",
        f"【業主描述】{draft['description'] or '（沒有填）'}",
        "【初步印象】\n" + _impressions_text(draft),
        "【問答】\n" + _qa_text(draft),
    ]
    if confirmed:
        parts.append(confirmed)
    if excerpts:
        parts.append("【網址節錄】\n\n" + "\n\n".join(excerpts))
    if missing_urls:
        parts.append(
            "【抓不到的網址】" + "、".join(missing_urls) + "——這幾個沒抓到內容，不要假裝查過。"
        )
    parts.append(
        "【禁止事項】你沒有網路，只能用上面給你的材料。佐證來源欄只能填上面出現過的網址，"
        "或「業主自述」「初掃印象」；推測不出來的就不要寫那一列，寧可少幾列。"
        "這一輪不整理「顧客原話」，總結表不要出現這個種類的列。"
    )
    parts.append(script.output_contract_block(known))
    return "\n\n".join(parts)


def _cost_estimate(depth: str) -> float:
    return script.COST_RESEARCH_DEEP if depth == "deep" else script.COST_RESEARCH_STANDARD


def _errors_text(errors) -> str:
    lines = []
    for e in errors or []:
        if isinstance(e, dict):
            where = f"第 {e['line']} 行：" if e.get("line") else ""
            lines.append(f"- {where}{e.get('msg') or ''}")
        else:
            lines.append(f"- {e}")
    return "\n".join(lines) or "- 讀不出總結表。"


def _reask_prompt(prompt: str, errors) -> str:
    return (
        prompt + "\n\n【上一次的回覆讀不出來】系統照上面的輸出格式讀你上一次的回覆，"
        "遇到這些問題：\n" + _errors_text(errors) + "\n"
        "請重新輸出一次，嚴格照上面的輸出格式，只輸出總結表。"
    )


def run_research(conn, draft: dict, depth: str) -> tuple:
    """回傳 (ok, needs_review)。ok=False：呼叫本身失敗（人話錯誤已經在 llm_task）。
    ok=True, needs_review=True：AI 有回覆，但 `apply_paste` 讀不出表格——原文已經存進
    `paste_raw`，使用者可以在進階摺疊裡自己修或讓外部 AI 重跑。

    F31-I02：第一次的回覆讀不出表格時，同一個工作裡自動再問一次（附上讀不出來的原因），
    這次一樣算進草稿的花費上限，上限不夠就不問；第二次還是讀不出來才走「格式要你看一下」。

    呼叫走既有的 `ai._run`（不重開第二個呼叫入口；它內部讀 `brand.knowledge_version`
    的那句 SQL 已經記在 `test_architecture_boundaries.KNOWN_SQL_VIOLATIONS` 裡）。"""
    existing = ir.existing_confirmed_data(conn, draft["brand_id"])
    prompt = build_prompt(conn, draft, existing)
    max_tokens = 16000 if depth == "deep" else 8000

    def ask(user_text: str) -> dict:
        return ai._run(
            conn, draft, task_type=TASK_TYPE, purpose="整理品牌知識",
            system=_SYSTEM, user_text=user_text,
            options=gateway.TaskOptions(max_tokens=max_tokens),
        )

    task = ask(prompt)
    if task["status"] != "succeeded":
        return False, False
    if state.apply_paste(draft, task["rendered_output"], conn=conn) is not None:
        return True, False
    draft = state.require_draft(draft["brand_id"], conn=conn)  # 重讀：花費已含第一次
    if state.would_exceed(draft, _cost_estimate(depth)):
        return True, True
    retry = ask(_reask_prompt(prompt, draft["paste_errors"]))
    if retry["status"] != "succeeded":
        return True, True
    return True, state.apply_paste(draft, retry["rendered_output"], conn=conn) is None


# ---------------------------------------------------------------------------
# 背景工作
# ---------------------------------------------------------------------------

def background_intake_research(org_id: str, brand_id: str, depth: str = "standard") -> None:
    with core_db_connection() as conn:
        brand = bi_repo.get_brand(conn, brand_id)
        brand_name = brand["name"] if brand else brand_id
        ok, needs_review, error = False, False, None
        try:
            draft = state.require_draft(brand_id, conn=conn)
            ok, needs_review = run_research(conn, draft, depth)
        except Exception as exc:  # noqa: BLE001 — 先寄失敗通知，再往上丟讓 job 記成失敗
            conn.rollback()  # 失敗的交易先收掉，通知才寫得進去
            ok, error = False, exc
        if ok:
            message = ("品牌知識整理完了，但格式要你看一下" if needs_review
                      else "品牌知識整理完了，可以回去看")
        else:
            message = "品牌知識整理失敗，可以回去重試"
        background_job.notify(
            conn, brand_id, category="intake_ai_step_done", dedupe_key=new_id("itkjob"),
            message=f"「{brand_name}」{message}", action_url=f"/app/brands/{brand_id}/intake",
        )
        if error is not None:
            raise error  # Contract J：job 結局要是 failed，狀態端點才不會讀成完成


def _start_research(brand_id: str, org_id: str, depth: str) -> None:
    lock = _lock(brand_id)
    if background_is_active(lock):
        return  # 已經在跑，no-op（跟 routes_api.py `_start` 同一個行為）
    background_enqueue(
        "background.intake_research", org_id=org_id, lock=lock, brand_id=brand_id, depth=depth,
    )


# ---------------------------------------------------------------------------
# 狀態（跟 routes_api.py 的 scan／question／paste_fix 狀態端點同一個形狀，自己一份小的
# 等價物——不 import routes_api，避免循環）
# ---------------------------------------------------------------------------

def _idle_job() -> dict:
    return {"status": "done", "stage": "", "started_at": now_iso(),
            "usual_range_text": "", "error": None}


def _job(status: str, started_at: str, error: str | None = None) -> dict:
    stage = {"running": "正在讀你填的網址並整理事實", "done": "完成",
              "failed": "正在讀你填的網址並整理事實"}[status]
    return {"status": status, "stage": stage, "started_at": started_at,
            "usual_range_text": _USUAL_RANGE_TEXT, "error": error}


def _failed_error(row: dict | None) -> str:
    """Contract J：job 失敗時，有那次呼叫留下的 llm_task 錯誤就用它，否則講背景程式。"""
    if row is not None and row["status"] not in ("running", "succeeded") and row["error"]:
        return row["error"]
    return JOB_FAILED_MESSAGE


def _latest_task_row(brand_id: str) -> dict | None:
    row = web.conn.execute(
        "SELECT * FROM llm_task WHERE brand_id = %s AND task_type = %s "
        "ORDER BY started_at DESC LIMIT 1",
        (brand_id, TASK_TYPE),
    ).fetchone()
    return dict(row) if row is not None else None


def job_state(draft: dict) -> dict:
    """Contract J 先看佇列：最新的 job 還在排／在跑＝running（即使有舊的 llm_task 列）；
    最新的 job 失敗＝failed。其餘照 llm_task 列判斷；成功列還要重驗格式：`apply_paste`
    讀不出表格時 `draft["paste_errors"]` 非空——比照 `routes_api._job_state` 對
    scan／question 的重驗方式。"""
    brand_id = draft["brand_id"]
    lock = _lock(brand_id)
    row = _latest_task_row(brand_id)
    outcome = background_job_outcome(lock)
    if outcome == "active":
        started = row["started_at"] if row is not None and row["status"] == "running" else None
        return _job("running", started.isoformat() if started else now_iso())
    if outcome == "failed":
        started = row["started_at"] if row is not None else None
        return _job("failed", started.isoformat() if started else now_iso(), _failed_error(row))
    if row is None:
        return _job("running", now_iso()) if background_is_active(lock) else _idle_job()
    started_at = row["started_at"].isoformat() if row["started_at"] else now_iso()
    if row["status"] == "running":
        return _job("running", started_at)
    if row["status"] != "succeeded":
        return _job("failed", started_at, row["error"] or "背景工作失敗，可以再試一次。")
    if background_is_active(lock):
        return _job("running", started_at)  # 主呼叫已成功，仍在做後續處理（apply_paste）
    if draft["paste_errors"]:
        return _job("failed", started_at,
                    "AI 有回覆，但格式讀不成預期的樣子。原文已經存起來，"
                    "可以到下面的進階摺疊自己修，或讓系統再花一點錢重新整理。")
    return _job("done", started_at)


def _limit_block(draft: dict, amount: float) -> dict:
    return {"kind": "research", "amount": amount, "cost_spent": draft["cost_spent"],
            "budget_limit": draft["budget_limit"],
            "suggested_limit": round(draft["budget_limit"] + 30, 2)}


# ---------------------------------------------------------------------------
# 端點
# ---------------------------------------------------------------------------

@router.post("/api/intake/brands/{brand_id}/research/start")
async def research_start(request: Request, brand_id: str):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    draft = state.require_draft(brand_id)
    body = await _json_body(request)
    raw_depth = body.get("depth")
    depth: str = raw_depth if raw_depth in ("standard", "deep") else "standard"
    amount = _cost_estimate(depth)
    if state.would_exceed(draft, amount):
        return {"limit_block": _limit_block(draft, amount)}
    _start_research(brand_id, actor.org_id, depth)
    return {"limit_block": None}


@router.get("/api/intake/brands/{brand_id}/research/status")
def research_status(request: Request, brand_id: str):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    draft = state.require_draft(brand_id)
    return _envelope(job_state(draft))
