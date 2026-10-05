"""app/workbench/free_parse.py — 自由創作「AI 解析結果」的唯一入口（container contract §1；
只有 `app/workbench/routes.py` 呼叫 `parse()`）。使用者按「建立自由工作」時打**一次**
`gateway.run_task`，把一段自由文字轉成建立任務包用的規格；打字的時候不打（那是呼叫端
`routes.py` 的責任，這裡只管一次呼叫）。

跟 `jobs.py` 分開：`jobs.py` 是 procrastinate 生成 job 的身體，這裡是請求路徑上的同步呼叫，
兩邊各自的 `PROVIDER` 各自 mock（`.work/features/F02.md` Decisions），互不 import。

`TaskContext` 刻意是空的——`knowledge_item_ids=[]`，不呼叫 `context_compiler.compile()`：
這是抽取自由文字的形狀，不是品牌口吻，壓縮成本才不會讓每一次點擊都貴一次完整品牌上下文
的錢（`.work/features/F02.md` Decisions）。`TaskOptions(max_retries=0)`：使用者盯著一顆
轉圈圈的按鈕等，不是背景 worker 排隊，逾時就直接回退，不重試多等一輪。
"""

from app.brand_intelligence import repository as bi_repo
from app.core.db import APP_DIR
from app.llm import gateway, providers

DEPARTMENT_PATH = APP_DIR / "departments" / "workbench" / "free_parse.md"

# 唯一的供應商實例，比照 app/workbench/jobs.py：測試用
# `mock.patch.object(free_parse, "PROVIDER", FakeProvider(...))` 換掉。
PROVIDER = providers.AnthropicProvider()

_VALID_PARTS = {"copy", "image_prompt", "video_script"}

# F50 Contract J: why a parse fell back. `llm_failed` carries the gateway's `error_code`.
REASONS = {
    "llm_failed": "AI 這次沒有回覆",
    "reply_unreadable": "回覆不是看得懂的格式",
    "reply_invalid": "回覆裡沒有可以用的產出項目",
}
# The plain words for an `llm_failed` row's `error_code` (`gateway.ERROR_CODES`).
_LLM_ERROR_WORDS = {
    "timeout": "等太久沒有回應",
    "refused": "AI 婉拒了這段描述",
    "provider": "AI 服務出錯",
    "truncated": "回覆太長被截斷",
    "spend_cap": "已到 AI 花費上限",
    "no_credentials": "還沒設定 AI 金鑰",
}


def not_parsed_note(reason: str, error_code: str | None = None) -> str:
    """The one fallback sentence, naming why (「AI 這次沒有讀懂（…），先照預設往下」)."""
    words = REASONS[reason]
    if reason == "llm_failed" and error_code in _LLM_ERROR_WORDS:
        words = _LLM_ERROR_WORDS[error_code]
    return f"AI 這次沒有讀懂（{words}），先照預設往下。"


def _valid_outputs(outputs) -> list | None:
    if not isinstance(outputs, list) or not outputs:
        return None
    result = []
    for item in outputs:
        if not isinstance(item, dict):
            return None
        part = item.get("part")
        if part not in _VALID_PARTS:
            return None
        count = item.get("count", 1)
        if count is None:
            count = 1
        if not isinstance(count, int) or isinstance(count, bool) or not (1 <= count <= 30):
            return None
        result.append({"part": part, "count": count})
    return result


def _string_or_none(value):
    return value if isinstance(value, str) and value else None


def _validate_reply(data) -> dict | None:
    if not isinstance(data, dict):
        return None
    outputs = _valid_outputs(data.get("outputs"))
    if outputs is None:
        return None
    return {
        "topic": _string_or_none(data.get("topic")),
        "outputs": outputs,
        # F07-I09（Decision 25）：舊全域風格庫退休，這個鍵永遠是 `None`——保留鍵本身只是
        # 因為腳本化的 e2e 回覆還帶著它，`_merged_spec()` 才有東西可以合併。
        "style_hint": None,
        "platform": _string_or_none(data.get("platform")),
        "size": _string_or_none(data.get("size")),
        "audience": _string_or_none(data.get("audience")),
        "key_message": _string_or_none(data.get("key_message")),
    }


def _merged_spec(defaults: dict, parsed: dict) -> dict:
    """模型贏每一個欄位，`null`（下面過濾成的 `None`）留住 `defaults` 原本的值——使用者
    在表單上已經填的東西，模型沒提到的部分不會被清空。"""
    spec = dict(defaults or {})
    for key, value in parsed.items():
        if value is not None:
            spec[key] = value
    return spec


def parse(conn, *, brand_id: str, free_text: str, defaults: dict) -> dict:
    """回傳 `{"parsed": bool, "note": str|None, "spec": dict}`。一次 `gateway.run_task`；
    逾時、失敗、非 JSON 或形狀不合的回覆一律回退到 `defaults`——**永不是死路**（票面
    「失敗是永遠不是死路」那條規則）：呼叫端拿到 `parsed: false` 照樣可以按下一步。

    F50 Contract J: a fallback also carries `reason` (a key of `REASONS`) and `error_code`
    (the `llm_task.error_code` for `llm_failed`, else None), and its `note` names the reason.
    A reply the program refused is recorded on its row with `gateway.record_refusal`."""
    department_text = DEPARTMENT_PATH.read_text(encoding="utf-8")
    prompt = department_text + "\n\n## 這段自由描述\n\n" + free_text

    brand_row = bi_repo.get_brand(conn, brand_id)
    context = gateway.TaskContext(
        context_scope={"brand_id": brand_id}, knowledge_item_ids=[],
        brand_version=brand_row["knowledge_version"] if brand_row else 1,
    )
    task_row = gateway.run_task(
        conn, PROVIDER, brand_id=brand_id, task_type="workbench_free_parse",
        prompt_template_id="workbench_free_parse", prompt_template_version="v1",
        system=None, messages=[{"role": "user", "content": prompt}], context=context,
        options=gateway.TaskOptions(max_tokens=2000, timeout_s=60.0, max_retries=0),
    )

    def fallback(reason: str, error_code: str | None = None) -> dict:
        return {"parsed": False, "reason": reason, "error_code": error_code,
                "note": not_parsed_note(reason, error_code), "spec": dict(defaults or {})}

    if task_row["status"] != "succeeded":
        return fallback("llm_failed", task_row.get("error_code"))

    data = gateway.parse_json_reply(task_row.get("rendered_output") or "")
    parsed = _validate_reply(data) if data is not None else None
    if parsed is None:
        reason = "reply_unreadable" if data is None else "reply_invalid"
        gateway.record_refusal(conn, task_row["id"], reason, REASONS[reason])
        return fallback(reason)

    return {"parsed": True, "note": None, "spec": _merged_spec(defaults, parsed)}
