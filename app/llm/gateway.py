"""app/llm/gateway.py — run_task：LLM 任務的唯一入口，寫 llm_task 記錄、算成本、處理重試。

見 docs/design/06-llm-gateway.md §9–14、docs/design/03-data-model.md §3.1 llm_task。

職責（本輪 skeleton，非完整 8 個統一函式——那些是下一輪精靈的消費者，見任務指示）：
1. 建 llm_task 列（status=running），記 brand_id、task_type、context_scope_json、
   knowledge_item_ids_json、brand_version/product_version、prompt_template_id/version、
   provider、model、attempt_no。
2. 呼叫 provider.complete()（timeout 預設 300s，來源見 TaskOptions.timeout_s）。
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
from dataclasses import dataclass

from app.brand_intelligence import repository as bi_repo
from app.core import db, settings
from app.llm import pricing, providers
from app.llm.providers import Provider, ProviderError, ProviderTimeoutError, SpendCapExceededError


def parse_json_reply(text: str):
    """模型回覆 → JSON。從第一個 { 或 [（誰先出現算誰）往後解「一個」完整的 JSON 值。

    raw_decode 只認那一個起點：解不完整就回 None，不會退而求其次撿內層的陣列或物件。
    舊版「第一個 { 到最後一個 }」的切片法在模型少收一個括號時會落到 [ ] 分支，撿到內層的
    branches 陣列，把「JSON 不完整」誤報成「形狀不對」；單元素的頂層陣列也會被 { } 分支
    切成第一個元素（customer_voice 的一句話萃取因此被靜靜丟掉）。兩種錯法都不會再發生。
    圍欄不必先剝：```json 落在第一個 { 之前、收尾的 ``` 落在值結束之後，都在解析範圍外。
    """
    text = text or ""
    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if not starts:
        return None
    try:
        return json.JSONDecoder().raw_decode(text, min(starts))[0]
    except ValueError:
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
    product_version: int | None = None


@dataclass
class TaskOptions:
    model: str | None = None  # None → 任務預設 > 設定頁選的模型（見 providers.resolve_model）
    thinking: str | None = None  # None → 任務預設 > 中檔（見 providers.resolve_thinking，票 #27）
    max_tokens: int = 16000
    # 300 秒的來源是本系統自己的量測，不是猜的：llm_task 列 llm_01M168X5443Y7PGV5D5ZDE2J1W
    # （schedule_plan，thinking=high＋網路搜尋 2 次）實測 170.57 秒產出 9,186 個 output token
    # ＝53.9 tok/s；同一個 dataclass 允許的 max_tokens=16000 除以這個速率＝297 秒，取整 300。
    # 交叉驗算：rule card schedule_plan_count 上限 5 個方案是實測 3 個的 1.67 倍＝284 秒。
    # 天花板 600 秒——SDK 非串流呼叫的上限（anthropic/_base_client.py:769-777），本路徑走
    # client.messages.create()，超過 600 秒是要改設計不是改數字。逾時是天花板不是目標：
    # 170 秒的呼叫在 300 秒天花板下一樣是 170 秒回來，放寬不會讓快的任務變慢。
    timeout_s: float = 300.0
    max_retries: int = 1  # 失敗重試次數（不含第一次嘗試；06 §11：MVP 同供應商內重試）
    # 這次呼叫要掛的工具（ADR 0005）。None＝不掛任何工具，送出的 request body 完全不變；
    # 要開網路搜尋就傳 [providers.WEB_SEARCH_TOOL]，由呼叫端逐一決定。
    tools: list | None = None


def get_task(conn: db.Conn, task_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM llm_task WHERE id = %s", (task_id,)).fetchone()
    return dict(row) if row is not None else None


def _insert_running_row(
    conn: db.Conn, *, org_id: str, brand_id: str, task_type: str, context: TaskContext,
    prompt_template_id: str, prompt_template_version: str, provider_name: str, model: str,
    attempt_no: int,
) -> dict:
    row_id = db.new_id("llm")
    ts = db.now_utc()
    # 輸入內容雜湊：對已排序的 knowledge_item_ids 取 sha256，供重現比對（03 §3.1）；
    # 純雜湊輸入不是欄位值，維持 json.dumps。
    input_context_hash = hashlib.sha256(
        json.dumps(sorted(context.knowledge_item_ids), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    conn.execute(
        """INSERT INTO llm_task (
            id, org_id, brand_id, task_type, context_scope_json, input_context_ids_json, input_context_hash,
            knowledge_item_ids_json, brand_version, product_version, campaign_plan_version,
            prompt_template_id, prompt_template_version, provider, model, status, attempt_no,
            structured_output_json, rendered_output, validation_result_json, usage_json, cost,
            started_at, finished_at, error
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, %s, %s, %s, %s, 'running', %s,
                   NULL, NULL, NULL, NULL, NULL, %s, NULL, NULL)""",
        (
            row_id, org_id, brand_id, task_type,
            db.jsonb(context.context_scope),
            db.jsonb(context.knowledge_item_ids), input_context_hash,
            db.jsonb(context.knowledge_item_ids),
            context.brand_version, context.product_version,
            prompt_template_id, prompt_template_version, provider_name, model, attempt_no, ts,
        ),
    )
    conn.commit()
    return get_task(conn, row_id)


def _mark_succeeded(conn: db.Conn, row_id: str, *,
                     structured_output: dict | None, rendered_output: str,
                     usage: dict, cost: float) -> None:
    conn.execute(
        "UPDATE llm_task SET status = 'succeeded', structured_output_json = %s, rendered_output = %s, "
        "usage_json = %s, cost = %s, finished_at = %s WHERE id = %s",
        (
            db.jsonb(structured_output) if structured_output is not None else None,
            rendered_output,
            db.jsonb(usage),
            cost,
            db.now_utc(),
            row_id,
        ),
    )
    conn.commit()


def _mark_failed(conn: db.Conn, row_id: str, *, status: str, error: str) -> None:
    conn.execute(
        "UPDATE llm_task SET status = %s, error = %s, finished_at = %s WHERE id = %s",
        (status, error, db.now_utc(), row_id),
    )
    conn.commit()


def run_task(
    conn: db.Conn,
    provider: Provider,
    *,
    brand_id: str,
    task_type: str,
    prompt_template_id: str,
    prompt_template_version: str,
    system: str | None,
    messages: list,
    context: TaskContext,
    options: TaskOptions | None = None,
) -> dict:
    """執行一次 LLM 任務，回傳最終的 llm_task 資料列（dict）。

    呼叫端請依回傳值的 row["status"] 判斷成敗（"succeeded" / "failed" / "timeout"），
    本函式不拋例外偽裝結果——除非傳入參數本身不合法（ValueError，例如缺 brand_id）。
    """
    if not brand_id:
        raise ValueError("brand_id 為必填")
    if not task_type:
        raise ValueError("task_type 為必填")

    # org_id 由 brand_id 反查（票 03-1）：app.llm 排在 app.brand_intelligence 之後
    # （LAYER_ORDER），可以直接 import 該層取值，不必逐層往上傳——run_task() 是全站
    # 呼叫點最多的入口之一，逐層傳參數會牽動幾十個呼叫端的簽章。
    brand = bi_repo.get_brand(conn, brand_id)
    if brand is None:
        raise ValueError(f"找不到品牌：{brand_id}")
    org_id = brand["org_id"]

    # 組織每月 AI 花費上限（票 04-1a，D4-2／D4-3）：在還沒寫入 llm_task 列、還沒打
    # provider 之前擋下——命中就沒有任何一筆多出來的紀錄或費用。只有 cap_applies=True
    # （'platform' 層，操作者付錢）才擋；'own' 層的組織自己付錢，上限只是參考數字，
    # 見 resolve_ai_credentials()。已經在跑的那次呼叫不受影響，只擋下一次。
    ai_creds = settings.resolve_ai_credentials(conn, org_id=org_id)
    if ai_creds.cap_applies:
        limit = settings.get_ai_monthly_cost_limit(conn, org_id=org_id)
        since = db.now_utc().strftime("%Y-%m-01T00:00:00")
        spent = settings.org_ai_spent_this_month(conn, org_id=org_id, since=since)
        if spent >= limit:
            raise SpendCapExceededError(
                f"這個月的 AI 用量已達上限（US$ {spent:.2f}／US$ {limit:.2f}），"
                "到「設定」頁調整上限後才能繼續。"
            )

    opts = options or TaskOptions()
    model = providers.resolve_model(opts.model, task_type=task_type, conn=conn, brand_id=brand_id)
    thinking = providers.resolve_thinking(opts.thinking, task_type=task_type)
    provider = providers.select_provider(provider)  # 開發用 codex_cli 開關，見 providers.py 開頭
    provider_name = getattr(provider, "name", "unknown")

    # 思考等級（票 #27）、工具（ADR 0005）、org_id（票 04-0：AnthropicProvider 讀 DB 金鑰
    # 要分租戶）都只在 provider.complete() 真的接受該參數時才傳——保留舊版 Provider 實作
    # （例如測試檔裡手寫、只認 5 個既有參數的假 Provider）不用跟著改也能繼續動。
    try:
        accepted = inspect.signature(provider.complete).parameters
    except (TypeError, ValueError):
        accepted = {}
    provider_accepts_effort = "effort" in accepted
    provider_accepts_tools = "tools" in accepted
    provider_accepts_org_id = "org_id" in accepted

    max_attempts = 1 + max(opts.max_retries, 0)
    row = None
    for attempt_no in range(1, max_attempts + 1):
        row = _insert_running_row(
            conn, org_id=org_id, brand_id=brand_id, task_type=task_type, context=context,
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
            if provider_accepts_tools and opts.tools:
                complete_kwargs["tools"] = opts.tools
            if provider_accepts_org_id:
                complete_kwargs["org_id"] = org_id
            response = provider.complete(**complete_kwargs)
        except ProviderTimeoutError as exc:
            _mark_failed(conn, row["id"], status="timeout", error=str(exc))
            row = get_task(conn, row["id"])
            continue
        except ProviderError as exc:
            _mark_failed(conn, row["id"], status="failed", error=str(exc))
            row = get_task(conn, row["id"])
            continue

        # 舊版 Provider 實作（測試檔裡手寫的假 Provider）可能回傳沒有 web_search_requests
        # 欄位的 Usage，用 getattr 取值，缺就當 0。search_sources 同理（票 08：不是每個
        # Provider 實作都會填這個欄位），沒有就存空清單，不是 null——呼叫端不必再判斷
        # None／[] 兩種「沒有」。usage_json 本來就是給對帳與除錯用的自由格式欄位
        # （schema 沒有per-card 結構），加這個鍵不是 schema 變更，不必開 migration。
        web_search_requests = getattr(response.usage, "web_search_requests", 0) or 0
        usage = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "cache_read_input_tokens": response.usage.cache_read_input_tokens,
            "cache_creation_input_tokens": response.usage.cache_creation_input_tokens,
            "web_search_requests": web_search_requests,
            "search_sources": getattr(response, "search_sources", None) or [],
        }
        # 網路搜尋按次另外收費（ADR 0005），token 費之外要加上去，llm_task.cost 才是這次呼叫
        # 的真實花費——全站花費上限讀的就是這個欄位的總和。
        cost = (
            pricing.calculate_cost(model, response.usage.input_tokens, response.usage.output_tokens)
            + web_search_requests * pricing.WEB_SEARCH_USD_PER_SEARCH
        )
        # 2026-08-29：`stop_reason == "max_tokens"` 代表模型還沒講完就被 max_tokens 切斷，
        # 回來的是半句 JSON。以前這裡照樣寫 succeeded，呼叫端拿到解不開的字串，只能回報
        # 「代理沒有回傳看得懂的東西」——把「超過長度上限」講成「模型亂回」，看的人完全
        # 不知道該調哪個旋鈕。實測 llm_01M16CM5CS8Q435MVWEJ5BYA9D：output_tokens 剛好
        # 16000，字串停在 `"value": "最大化轉換次`。截斷是失敗，而且要說出是哪一種失敗。
        if getattr(response, "stop_reason", None) == "max_tokens":
            # 失敗歸失敗，錢照記：這些 token 真的生成過、真的計費了。只寫 error 不寫 cost，
            # 等於再犯一次今天稍早修掉的「花費上限少算」（見本檔 providers 的 max_retries
            # 註解）——那次是重試漏記，這次會變成截斷漏記，同一個洞的兩個入口。
            conn.execute(
                "UPDATE llm_task SET rendered_output = %s, usage_json = %s, cost = %s "
                "WHERE id = %s",
                (response.output_text, db.jsonb(usage), cost, row["id"]),
            )
            _mark_failed(
                conn, row["id"], status="failed",
                error=(f"產出超過長度上限（{opts.max_tokens} tokens）被截斷，這次的內容不完整。"
                       "請提高該任務的 max_tokens，或把要產出的東西拆小。"),
            )
            return get_task(conn, row["id"]) or {}
        _mark_succeeded(
            conn, row["id"], structured_output=response.structured,
            rendered_output=response.output_text, usage=usage, cost=cost,
        )
        return get_task(conn, row["id"])

    # 全部嘗試皆失敗（含最後一次）——回傳最後一列失敗記錄，不拋例外偽裝成功。
    return row
