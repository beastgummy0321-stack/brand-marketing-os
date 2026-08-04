# -*- coding: utf-8 -*-
"""app/llm/gateway.py — run_task：LLM 任務的唯一入口，寫 llm_task 記錄、算成本、處理重試。

見 docs/design/06-llm-gateway.md §9–14、docs/design/03-data-model.md §3.1 llm_task。

職責（本輪 skeleton，非完整 8 個統一函式——那些是下一輪精靈的消費者，見任務指示）：
1. 建 llm_task 列（status=running），記 brand_id、task_type、context_scope_json、
   knowledge_item_ids_json、brand_version/product_version、prompt_template_id/version、
   provider、model、attempt_no。
2. 呼叫 provider.complete()（timeout 預設 120s）。
3. 成功：寫 structured_output_json／rendered_output／usage_json／cost／finished_at，
   status=succeeded；逐字保留模型輸出，不改寫（principles 第 2 條）。
4. 失敗：寫 error／finished_at，status=failed 或 timeout；失敗重試 1 次，
   重試＝新的一列 llm_task（attempt_no+1），不冒充前次（principles 第 6 條）。
5. 全部嘗試皆失敗時，回傳最後一次嘗試的（失敗）列——不拋例外偽裝成功，也不編造內容
   （誠實狀態，principles 第 16 條）；呼叫端依 row["status"] 判斷。
"""

import hashlib
import inspect
import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Optional

from app.core import db
from app.llm import pricing, providers
from app.llm.providers import Provider, ProviderError, ProviderTimeoutError


def parse_json_reply(text: str):
    """模型回覆 → JSON。容忍圍欄與前後贅字：抓第一個 { 或 [ 到最後一個對應括號。

    原本是 app/intake/ai.py 的私有函式，報告生成（app/brand_intelligence/report.py）
    需要同一套解析邏輯，搬到這裡公開後兩邊共用一份（ai.py 保留別名，行為零變化）。
    """
    text = re.sub(r"```(?:json)?", "", text or "").strip()
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = text.find(open_ch)
        end = text.rfind(close_ch)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except ValueError:
                continue
    return None


@dataclass
class TaskContext:
    """落地到 llm_task 的上下文中介資訊（對齊 06 §7 CompiledContext 的必要子集）。

    通常由 context_compiler.compile() 的回傳值組裝而成：
        text, knowledge_item_ids, brand_version, product_version = context_compiler.compile(...)
        context = TaskContext(context_scope={"brand_id": brand_id, "product_id": product_id},
                               knowledge_item_ids=knowledge_item_ids,
                               brand_version=brand_version, product_version=product_version)
    """

    context_scope: dict
    knowledge_item_ids: list
    brand_version: int
    product_version: Optional[int] = None


@dataclass
class TaskOptions:
    model: Optional[str] = None  # None → 任務預設 > 設定頁選的模型（見 providers.resolve_model）
    thinking: Optional[str] = None  # None → 任務預設 > 中檔（見 providers.resolve_thinking，票 #27）
    max_tokens: int = 16000
    timeout_s: float = 120.0
    max_retries: int = 1  # 失敗重試次數（不含第一次嘗試；06 §11：MVP 同供應商內重試）


def get_task(conn: sqlite3.Connection, task_id: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM llm_task WHERE id = ?", (task_id,)).fetchone()
    return dict(row) if row is not None else None


def _insert_running_row(
    conn: sqlite3.Connection, *, brand_id: str, task_type: str, context: TaskContext,
    prompt_template_id: str, prompt_template_version: str, provider_name: str, model: str,
    attempt_no: int,
) -> dict:
    row_id = db.new_id("llm")
    ts = db.now_iso()
    knowledge_item_ids_json = json.dumps(context.knowledge_item_ids, ensure_ascii=False)
    # 輸入內容雜湊：對已排序的 knowledge_item_ids 取 sha256，供重現比對（03 §3.1）。
    input_context_hash = hashlib.sha256(
        json.dumps(sorted(context.knowledge_item_ids), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    conn.execute(
        """INSERT INTO llm_task (
            id, brand_id, task_type, context_scope_json, input_context_ids_json, input_context_hash,
            knowledge_item_ids_json, brand_version, product_version, campaign_plan_version,
            prompt_template_id, prompt_template_version, provider, model, status, attempt_no,
            structured_output_json, rendered_output, validation_result_json, usage_json, cost,
            started_at, finished_at, error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, 'running', ?,
                   NULL, NULL, NULL, NULL, NULL, ?, NULL, NULL)""",
        (
            row_id, brand_id, task_type,
            json.dumps(context.context_scope, ensure_ascii=False),
            knowledge_item_ids_json, input_context_hash, knowledge_item_ids_json,
            context.brand_version, context.product_version,
            prompt_template_id, prompt_template_version, provider_name, model, attempt_no, ts,
        ),
    )
    conn.commit()
    return get_task(conn, row_id)


def _mark_succeeded(conn: sqlite3.Connection, row_id: str, *,
                     structured_output: Optional[dict], rendered_output: str,
                     usage: dict, cost: float) -> None:
    conn.execute(
        "UPDATE llm_task SET status = 'succeeded', structured_output_json = ?, rendered_output = ?, "
        "usage_json = ?, cost = ?, finished_at = ? WHERE id = ?",
        (
            json.dumps(structured_output, ensure_ascii=False) if structured_output is not None else None,
            rendered_output,
            json.dumps(usage, ensure_ascii=False),
            cost,
            db.now_iso(),
            row_id,
        ),
    )
    conn.commit()


def _mark_failed(conn: sqlite3.Connection, row_id: str, *, status: str, error: str) -> None:
    conn.execute(
        "UPDATE llm_task SET status = ?, error = ?, finished_at = ? WHERE id = ?",
        (status, error, db.now_iso(), row_id),
    )
    conn.commit()


def run_task(
    conn: sqlite3.Connection,
    provider: Provider,
    *,
    brand_id: str,
    task_type: str,
    prompt_template_id: str,
    prompt_template_version: str,
    system: Optional[str],
    messages: list,
    context: TaskContext,
    options: Optional[TaskOptions] = None,
) -> dict:
    """執行一次 LLM 任務，回傳最終的 llm_task 資料列（dict）。

    呼叫端請依回傳值的 row["status"] 判斷成敗（"succeeded" / "failed" / "timeout"），
    本函式不拋例外偽裝結果——除非傳入參數本身不合法（ValueError，例如缺 brand_id）。
    """
    if not brand_id:
        raise ValueError("brand_id 為必填")
    if not task_type:
        raise ValueError("task_type 為必填")

    opts = options or TaskOptions()
    model = providers.resolve_model(opts.model, task_type=task_type, conn=conn)
    thinking = providers.resolve_thinking(opts.thinking, task_type=task_type)
    provider_name = getattr(provider, "name", "unknown")

    # 思考等級只在 provider.complete() 真的接受 effort 參數時才傳——保留舊版 Provider
    # 實作（例如測試檔裡手寫、只認 5 個既有參數的假 Provider）不用跟著改也能繼續動。
    try:
        provider_accepts_effort = "effort" in inspect.signature(provider.complete).parameters
    except (TypeError, ValueError):
        provider_accepts_effort = False

    max_attempts = 1 + max(opts.max_retries, 0)
    row = None
    for attempt_no in range(1, max_attempts + 1):
        row = _insert_running_row(
            conn, brand_id=brand_id, task_type=task_type, context=context,
            prompt_template_id=prompt_template_id, prompt_template_version=prompt_template_version,
            provider_name=provider_name, model=model, attempt_no=attempt_no,
        )
        try:
            complete_kwargs = {
                "model": model, "system": system, "messages": messages,
                "max_tokens": opts.max_tokens, "timeout_s": opts.timeout_s,
            }
            if provider_accepts_effort:
                complete_kwargs["effort"] = thinking
            response = provider.complete(**complete_kwargs)
        except ProviderTimeoutError as exc:
            _mark_failed(conn, row["id"], status="timeout", error=str(exc))
            row = get_task(conn, row["id"])
            continue
        except ProviderError as exc:
            _mark_failed(conn, row["id"], status="failed", error=str(exc))
            row = get_task(conn, row["id"])
            continue

        usage = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "cache_read_input_tokens": response.usage.cache_read_input_tokens,
            "cache_creation_input_tokens": response.usage.cache_creation_input_tokens,
        }
        cost = pricing.calculate_cost(model, response.usage.input_tokens, response.usage.output_tokens)
        _mark_succeeded(
            conn, row["id"], structured_output=response.structured,
            rendered_output=response.output_text, usage=usage, cost=cost,
        )
        return get_task(conn, row["id"])

    # 全部嘗試皆失敗（含最後一次）——回傳最後一列失敗記錄，不拋例外偽裝成功。
    return row
