"""app/llm/providers.py — Provider 介面（供應商中立）＋兩個實作。

原始文件已被 5eca0db 清除；權威現在是這支檔案的 Provider 介面本身。

Provider.complete() 只做「供應商 SDK 呼叫 → 統一回傳物件」的轉換，不改寫模型輸出內容
（薄殼原則，principles 第 2 條）。上層 gateway 永不接觸供應商原生型別，只認識這裡的
ProviderResponse／ProviderError。
"""

from __future__ import annotations

import base64
import contextvars
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.brand_intelligence import repository as bi_repo
from app.core import config, settings
from app.llm import pricing

# 缺金鑰的人話訊息：不出現環境變數名（使用者看不懂），一律指向設定頁（07 §3 規則 3）。
MISSING_KEY_MESSAGE = "尚未設定 AI 金鑰，請到「設定」頁填入後再試一次"

# ---------------------------------------------------------------------------
# 本機 Codex CLI 線路（內部測試用，非正式版功能）：正式版仍走 Anthropic。
# BRAND_OS_LLM_PROVIDER=codex_cli 時，LLM 呼叫改走本機 codex 指令、走 ChatGPT 訂閱額度，
# 不產生 API 帳單；沒設這個環境變數就完全維持現狀。模型固定 gpt-5.6-luna，刻意不放進
# app/shared/web.py 的 MODEL_CHOICES（正式版選單不該看得到它）。
# ---------------------------------------------------------------------------
CODEX_CLI_MODEL = "gpt-5.6-luna"

# ---------------------------------------------------------------------------
# 罐頭回覆線路（e2e 後端專用，F06-I05）：BRAND_OS_LLM_PROVIDER=scripted 時，每一次 AI 呼叫
# 都回這張表裡按 task_type 對應的固定 JSON，不打任何真實模型。只收 e2e 請求路徑上真的會打的
# 三種 task_type；沒有腳本的 task_type 在 select_provider() 選供應商時就丟 LookupError，
# 讓請求 500、e2e 當場紅，不會掉進「解析失敗改用預設值」那條安靜的退路。
# ---------------------------------------------------------------------------
SCRIPTED_REPLIES: dict[str, dict] = {
    "ads_brief_parse": {
        "objective": "購買", "success_metric": "roas", "success_target": None,
        "success_basis": "e2e scripted reply", "product_ids": [], "audience_hint": None,
        "notes": None, "budget_cap": None, "platform": None, "period": None,
    },
    "ads_strategy": {
        "allocation": [
            {"role": "new", "pct": 50, "rationale": "e2e scripted reply"},
            {"role": "retarget", "pct": 30, "rationale": "e2e scripted reply"},
            {"role": "explore", "pct": 20, "rationale": "e2e scripted reply"},
        ],
        "why": ["e2e scripted reply"], "unknowns": [], "alternatives": [], "learning_goals": [],
    },
    "workbench_free_parse": {
        "topic": None, "outputs": [{"part": "image_prompt", "count": 1}], "style_hint": None,
        "platform": None, "size": None, "audience": None, "key_message": None,
    },
}


def codex_cli_enabled() -> bool:
    """環境變數開著＝這次呼叫要換走本機 Codex CLI 線路，不用猜也不用查其他旗標。"""
    return config.settings().brand_os_llm_provider == "codex_cli"


def select_provider(provider: Provider, task_type: str | None = None) -> Provider:
    """codex_cli_enabled() 開著時換成 CodexCliProvider，`BRAND_OS_LLM_PROVIDER=scripted` 時
    換成 ScriptedProvider（e2e 後端專用，F06-I05），否則原樣回傳既有 provider——給每個呼叫端
    （gateway.run_task、設定頁測試連線、intake 操作卡實測工具）共用同一個切換點，不必各自
    重寫判斷式。"""
    if config.settings().brand_os_llm_provider == "scripted":
        if task_type not in SCRIPTED_REPLIES:
            raise LookupError(
                f"scripted provider has no reply for task_type {task_type!r}; "
                "add one to SCRIPTED_REPLIES in app/llm/providers.py"
            )
        return ScriptedProvider(SCRIPTED_REPLIES[task_type])
    if codex_cli_enabled():
        return CodexCliProvider()
    return provider


def to_strict_schema(schema: dict) -> dict:
    """Anthropic 工具用的 input_schema（JSON Schema 子集）→ OpenAI strict 模式版本。

    OpenAI strict 模式規定 properties 內每個鍵都要出現在 required 裡（實測：漏列會回 400，
    'required' is required to be supplied and to be an array including every key in
    properties）。本來非必填的欄位改成「列入 required，但型別／enum 加上 null」頂替
    （實測可行）。純函式，不連網、不吃 I/O，遞迴處理巢狀 object／array。
    """
    if not isinstance(schema, dict):
        return schema
    schema = dict(schema)
    if schema.get("type") == "object" and isinstance(schema.get("properties"), dict):
        properties = schema["properties"]
        required_now = set(schema.get("required") or [])
        new_properties = {}
        for key, subschema in properties.items():
            converted = to_strict_schema(subschema)
            if key not in required_now:
                converted = _make_nullable(converted)
            new_properties[key] = converted
        schema["properties"] = new_properties
        schema["required"] = list(properties.keys())
        schema.setdefault("additionalProperties", False)
    elif schema.get("type") == "array" and isinstance(schema.get("items"), dict):
        schema["items"] = to_strict_schema(schema["items"])
    return schema


def _make_nullable(schema: dict) -> dict:
    """把一個欄位的 schema 改成型別（與 enum，如果有）多容許 null——OpenAI strict 模式
    表達「非必填」的方式：必須列進 required，但值可以是 null。"""
    schema = dict(schema)
    field_type = schema.get("type")
    if isinstance(field_type, str):
        schema["type"] = [field_type, "null"]
    elif isinstance(field_type, list) and "null" not in field_type:
        schema["type"] = [*field_type, "null"]
    if isinstance(schema.get("enum"), list) and None not in schema["enum"]:
        schema["enum"] = [*schema["enum"], None]
    return schema

# Anthropic Vision 官方格式與限制（查證日 2026-08-15）：Messages 的 user content 使用
# image block，base64 source 需帶 media_type／data；直接 Claude API 的單張 base64 編碼後上限
# 10 MB、最大尺寸 8000×8000 px，支援 JPEG／PNG／GIF／WebP；像素尺寸由 API 驗證，若拒絕
# 會由 gateway 留下失敗紀錄，照片卡顯示 failed。來源：
# https://platform.claude.com/docs/en/build-with-claude/vision
IMAGE_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "image/gif", "image/webp"})
MAX_BASE64_IMAGE_BYTES = 10 * 1024 * 1024


def base64_image_block(media_type: str, content: bytes) -> dict:
    """本機圖片位元組轉成 Anthropic Messages API 的官方 image content block。"""
    if media_type not in IMAGE_MEDIA_TYPES:
        raise ValueError("這張照片的格式不支援，請使用 JPG、PNG、GIF 或 WebP。")
    encoded = base64.b64encode(content).decode("ascii")
    if len(encoded.encode("ascii")) > MAX_BASE64_IMAGE_BYTES:
        raise ValueError("這張照片編碼後超過 10 MB，請換一張小一點的照片。")
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": encoded},
    }

# ---------------------------------------------------------------------------
# 模型與思考等級（票 #27）：任務 →（預設模型、思考等級）對照表＋當場覆寫。
# ---------------------------------------------------------------------------

# 思考等級固定五檔，字面值直接對齊 Anthropic API 的 output_config.effort（claude-api
# skill 查證：low/medium/high/xhigh/max），不用再另外轉換一次。
THINKING_LEVEL_ORDER = ["low", "medium", "high", "xhigh", "max"]
THINKING_LEVEL_LABELS = {
    "low": "低", "medium": "中", "high": "高", "xhigh": "超高", "max": "極高",
}
DEFAULT_THINKING_LEVEL = "medium"  # 任務不在對照表裡時的預設檔——不確定就留中檔

# 支援 output_config.effort 的模型。claude-api skill 查證：這個參數在 Sonnet 4.5／
# Haiku 4.5 這類舊模型上會被 API 拒絕（400），不能無腦對所有模型都送；claude-haiku-4-5
# 在本表刻意不列入。之後模型清單異動只需要調整這個集合，呼叫端不用動。
EFFORT_SUPPORTED_MODELS = {"claude-opus-5", "claude-sonnet-5", "claude-fable-5"}

# 任務 →（人話標籤、模型預設、思考等級預設）。model 為 None 代表沿用全域設定
# （settings 頁「使用的模型」）——目前只有思考等級依任務性質分檔，模型維持全站一致，
# 需要哪個任務換模型時再回來改這裡，不用動呼叫端。
TASK_TYPE_LABELS = {
    "schedule_plan": "檔期規劃（出方案）",
    "schedule_tree": "檔期規劃（展開活動樹，票 09）",
    "workbench_copy": "素材工作檯：文案",
    "workbench_image_prompt": "素材工作檯：圖片提示詞",
    "workbench_video_script": "素材工作檯：影片腳本",
    "workbench_free": "素材工作檯：自由生成",
    "workbench_derive_identity": "素材工作檯：品牌視覺推導",
    "intake_scan": "建檔精靈：讀取網址",
    "intake_photo_scan": "建檔精靈：讀取照片",
    "intake_persona": "建檔精靈：整理人物誌",
    "intake_question": "建檔精靈：追問",
    "intake_paste_fix": "建檔精靈：貼上格式修復",
    "intake_research": "建檔精靈：系統自動調研",
    "product_scan": "產品建檔：讀取網址",
    "product_handoff_fix": "產品交接：格式修復",
    "brand_report": "品牌智庫報告",
    "customer_voice_extraction": "顧客原話萃取",
    "performance_reading": "成效判讀",
    "settlement_diff_explanation": "補件重判差異說明",
}

TASK_DEFAULTS = {
    # 規劃：較高思考
    "schedule_plan": {"model": None, "thinking": "high"},
    "schedule_tree": {"model": None, "thinking": "high"},
    # 素材工作檯：文案較高思考，其餘三個中等思考（票 workbench/02，ADR 0068 §9）
    "workbench_copy": {"model": None, "thinking": "high"},
    "workbench_image_prompt": {"model": None, "thinking": "medium"},
    "workbench_video_script": {"model": None, "thinking": "medium"},
    "workbench_free": {"model": None, "thinking": "medium"},
    "workbench_derive_identity": {"model": None, "thinking": "medium"},
    # 機械性小任務：低思考
    "intake_scan": {"model": None, "thinking": "low"},
    "intake_photo_scan": {"model": None, "thinking": "low"},
    "intake_persona": {"model": None, "thinking": "medium"},
    "intake_question": {"model": None, "thinking": "low"},
    "intake_paste_fix": {"model": None, "thinking": "low"},
    "intake_research": {"model": None, "thinking": "high"},
    "product_scan": {"model": None, "thinking": "low"},
    "product_handoff_fix": {"model": None, "thinking": "low"},
    # 分析型任務：不確定，留中檔
    "brand_report": {"model": None, "thinking": "medium"},
    "customer_voice_extraction": {"model": None, "thinking": "medium"},
    "performance_reading": {"model": None, "thinking": "medium"},
    # 翻譯既有 diff 明細成人話，不做判斷：低思考即可
    "settlement_diff_explanation": {"model": None, "thinking": "low"},
}


def task_default_table() -> list:
    """設定頁顯示用的「任務 → 模型／思考等級」對照表（可視、可核對，票 #27 驗收 1）。"""
    rows = []
    for task_type, label in TASK_TYPE_LABELS.items():
        default = TASK_DEFAULTS.get(task_type, {})
        model = default.get("model")
        thinking = default.get("thinking", DEFAULT_THINKING_LEVEL)
        rows.append({
            "task_type": task_type,
            "task_label": label,
            "model_label": model or "沿用上面設定的模型",
            "thinking_label": THINKING_LEVEL_LABELS.get(thinking, thinking),
        })
    return rows


# 本次表單覆寫（票 #27）：生成按鈕旁選單當場改的值，只影響這一次呼叫、不落資料庫，
# 呼叫完立即清除。用 contextvar 而非模組全域變數，避免併發請求互相汙染——FastAPI
# 同步路由會跑在各自的 worker thread，anyio 會把呼叫當下的 context 複製過去，
# 因此同一個請求內設定、讀取都在同一份 context 副本上，彼此請求不會互相干擾。
_model_override_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "brand_os_model_override", default=None)
_thinking_override_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "brand_os_thinking_override", default=None)


class request_overrides:
    """with 區塊：本次生成呼叫改用指定的模型／思考等級，離開區塊自動清除。

    model／thinking 都要驗過白名單：model 不在 pricing.PRICING 這張唯一權威表裡
    （表單被動手腳、瀏覽器手改網址塞 model=hacked-model-xyz）、thinking 不在五檔內，
    一律視同沒填，退回任務預設，不噴錯、也不會真的打到供應商（票 #27 驗收 7；破壞者
    情境修復）。用 pricing.PRICING 當權威而不是 main.MODEL_CHOICES，避免 app.llm 反過來
    匯入 app.main 造成循環依賴。
    """

    def __init__(self, model: str | None = None, thinking: str | None = None):
        self._model = model if model in pricing.PRICING else None
        self._thinking = thinking if thinking in THINKING_LEVEL_ORDER else None

    def __enter__(self) -> request_overrides:
        self._model_token = _model_override_var.set(self._model)
        self._thinking_token = _thinking_override_var.set(self._thinking)
        return self

    def __exit__(self, *exc) -> bool:
        _model_override_var.reset(self._model_token)
        _thinking_override_var.reset(self._thinking_token)
        return False


def resolve_model(override: str | None = None, task_type: str | None = None,
                  conn=None, *, brand_id: str) -> str:
    """決定實際呼叫的模型，優先鏈：本次表單覆寫 > 任務預設 > 全域設定（票 #27）。

    全域設定＝ DB > 環境變數 > 預設值，見 core/settings。conn：手上已有資料庫連線時
    傳入（例如 gateway），沒有就讓 settings 自己開短命連線。

    每一層都要在 pricing.PRICING 白名單內才採用，非法值（表單覆寫、DB 設定值都算）
    視同沒填、往下一層退，不噴錯——避免手改網址塞不存在的 model 一路通到真的打 API
    （破壞者情境；與 resolve_thinking 同一套防線）。

    brand_id 必填（票 04-0）：全域設定現在依 org_id 分租戶存放，app.llm 依 LAYER_ORDER
    排在 app.brand_intelligence 之後，可以直接 import 該層反查 org_id，不必逐層往上傳
    （同 app/llm/gateway.py run_task() 既有的作法）。

    本機 Codex CLI 線路開著時（codex_cli_enabled()）無視上面整條優先鏈，一律回
    CODEX_CLI_MODEL——llm_task.model 因此記的是真的跑的那顆模型，不是設定頁選的那顆。
    """
    if codex_cli_enabled():
        return CODEX_CLI_MODEL
    if override in pricing.PRICING:
        return override
    request_override = _model_override_var.get()
    if request_override in pricing.PRICING:
        return request_override
    task_model = TASK_DEFAULTS.get(task_type, {}).get("model") if task_type else None
    if task_model in pricing.PRICING:
        return task_model
    org_id = bi_repo._org_id_for_brand(conn, brand_id)
    global_model = settings.get_llm_model(conn, org_id=org_id)
    if global_model in pricing.PRICING:
        return global_model
    return settings.DEFAULT_LLM_MODEL


def resolve_thinking(override: str | None = None, task_type: str | None = None) -> str:
    """決定實際使用的思考等級，優先鏈與 resolve_model 相同（票 #27）。

    非法值（不在五檔內）視同沒填，逐層退回，不噴錯（驗收 7）。
    """
    if override in THINKING_LEVEL_ORDER:
        return override
    request_override = _thinking_override_var.get()
    if request_override in THINKING_LEVEL_ORDER:
        return request_override
    task_thinking = TASK_DEFAULTS.get(task_type, {}).get("thinking") if task_type else None
    if task_thinking in THINKING_LEVEL_ORDER:
        return task_thinking
    return DEFAULT_THINKING_LEVEL


# ---------------------------------------------------------------------------
# 網路搜尋工具（ADR 0005）：同一份外部規格只准有一個真相來源，呼叫端一律引用這個常數。
# ---------------------------------------------------------------------------
# 欄位與型別字串全部照官方文件抄，不得自創：
# https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool.md
# （查證日 2026-08-11；不需要 beta header，web_search 是正式功能）
#
# type 為什麼選最基本的 web_search_20250305：官方目前有三個版本
# （20250305 基本／20260209 加動態過濾／20260318 再加 response_inclusion）。後兩個版本的
# allowed_callers 預設是 ["code_execution_20260120"]，只有 Claude 4.6 以後的模型支援；設定頁
# 的模型選單（app/shared/web.py MODEL_CHOICES）含 claude-haiku-4-5，用新版會在那台模型上被
# API 退回 400。基本版對四台模型都成立，一個常數走一條路、不依模型分岔。
# 代價：沒有動態過濾，搜尋結果整份進 prompt，輸入 token 比新版多。等模型選單不再有 4.6
# 以前的模型時可直接把 type 換成新版。
#
# max_uses：ADR 0005 指定 2–3，取 3。user_location.country 是 ISO 3166-1 alpha-2 兩碼。
WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
    "max_uses": 3,
    "user_location": {"type": "approximate", "country": "TW"},
}


class ProviderError(Exception):
    """統一錯誤型別：缺金鑰、供應商婉拒（refusal）、供應商錯誤都包成人話訊息後拋出這個型別。

    gateway 只需要認得這一個型別（及其子類別 ProviderTimeoutError），不用逐一認識
    供應商原生的例外階層。
    """


class ProviderTimeoutError(ProviderError):
    """逾時（對應 llm_task.status = timeout，與其他失敗的 status = failed 區分）。"""


class SpendCapExceededError(ProviderError):
    """這個月的 AI 花費已經到操作者付費上限（票 04-1a，D4-2／D4-3）。gateway.run_task()
    在還沒寫入 llm_task 列、還沒呼叫 provider.complete() 之前就拋出這個型別（在重試迴圈
    最外層，不是迴圈裡的 try/except 包住的那段），所以不會被當成一次失敗嘗試而重試、
    也不會有任何一筆多出來的紀錄或費用——跟 ProviderTimeoutError 一樣是 ProviderError
    的子類別，呼叫端不用另外認得一個新型別家族。"""


@dataclass
class Usage:
    """token 用量的統一形狀（原對齊文件已被 5eca0db 清除）。"""

    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    # 伺服器端工具用量：官方 usage.server_tool_use.web_search_requests（整數，出錯的搜尋
    # 不計入也不計費）。搜尋另外按次收費，成本要靠這個數字才算得出來（見 pricing.py）。
    web_search_requests: int = 0


@dataclass
class ProviderResponse:
    """統一回傳物件（本輪任務指示）：output_text／structured／usage／stop_reason／raw。

    output_text 與 structured 皆逐字來自模型，gateway 不得再改寫（principles 第 2 條）。

    search_sources（票 08）：網路搜尋工具（ADR 0005）成功時找到的結果，`[{"title", "url"}]`。
    沒開工具、開了但沒搜、或搜尋本身出錯，都是空清單——不是例外、不擋下這次任務（票 08 兩條
    不可妥協規則：查詢不是排程的先決條件；伺服器端工具出錯是 HTTP 200 帶錯誤物件，不是例外）。
    """

    output_text: str
    structured: dict | None
    usage: Usage
    stop_reason: str
    raw: object = None
    search_sources: list | None = None


class Provider(Protocol):
    """供應商中立介面：上層只依賴這個方法簽名，換供應商＝換一個實作（build.md 驗收 16）。"""

    name: str

    def complete(
        self,
        *,
        model: str,
        system: str | None,
        messages: list,
        max_tokens: int,
        timeout_s: float = 120.0,
        effort: str | None = None,
        tools: list | None = None,
        org_id: str | None = None,
    ) -> ProviderResponse: ...


class AnthropicProvider:
    """第一個實作（D3）：官方 anthropic Python SDK。延遲 import，避免未安裝時整包壞掉。

    - 金鑰：呼叫前經 settings.get_api_key() 取得（環境變數優先、DB 設定回退，修憲落地 M4），
      沒有金鑰時在打出網路請求前就拋出人話錯誤。不快取到模組層——設定頁改完金鑰要立刻生效（07 §3）。
      DB 回退依 org_id 分租戶存放（票 04-0）：`org_id` 在 Provider 介面上維持可選（同
      effort／tools 的假 Provider 相容寫法），但 AnthropicProvider 真的要打 DB 查金鑰，
      沒收到就整段拒絕——不會、也不能猜一個組織頂著用（那正是本票要修的洩漏）。
      `app/llm/gateway.py run_task()` 已經從 brand_id 反查出 org_id，經 kwargs 傳下來。
    - 目標模型 Claude Opus 5 預設即有思考、不傳 thinking 參數時就是 adaptive（claude-api
      skill 查證），因此本實作刻意不傳 temperature/top_p/top_k/thinking——但思考「深度」
      經 effort 參數控制（output_config.effort，票 #27），只在 EFFORT_SUPPORTED_MODELS
      清單內的模型才送，避免對不支援的模型（如 Haiku 4.5）送出會被拒絕的參數。
    - 回應處理：先檢查 stop_reason == "refusal" 再讀 content，refusal 一律轉成 ProviderError，
      不嘗試解析可能為空的 content。
    - 錯誤鏈由專到廣：RateLimitError → APIStatusError → APITimeoutError → APIConnectionError
      （Timeout 是 Connection 的子類別，須排在其前面才會先被攔截）。
    """

    name = "anthropic"

    def complete(
        self,
        *,
        model: str,
        system: str | None,
        messages: list,
        max_tokens: int,
        timeout_s: float = 120.0,
        effort: str | None = None,
        tools: list | None = None,
        org_id: str | None = None,
    ) -> ProviderResponse:
        # org_id 在介面上是可選（同 effort／tools，讓假 Provider 不必跟著改），但真的要
        # 打 DB 查金鑰時沒有它就是呼叫端沒把租戶身分傳下來——這是程式錯誤，不是「使用者
        # 沒設定金鑰」那種人話錯誤，直接炸掉，不猜一個組織頂著用（票 04-0 就是在修這個洩漏）。
        if org_id is None:
            raise ValueError("AnthropicProvider.complete() 缺 org_id：呼叫端沒有正確傳遞租戶身分")
        # 金鑰檢查放在 SDK import 之前：沒金鑰時連套件都不需要，就能給出人話錯誤。
        api_key = settings.get_api_key(org_id=org_id)
        if not api_key:
            raise ProviderError(MISSING_KEY_MESSAGE)

        import anthropic  # 延遲 import：本檔案本身不強制要求安裝此套件才能被 import

        kwargs = {"model": model, "max_tokens": max_tokens, "messages": messages}
        if system:
            kwargs["system"] = system
        if effort and model in EFFORT_SUPPORTED_MODELS:
            kwargs["output_config"] = {"effort": effort}
        # 沒傳工具就完全不放 tools 這個鍵——既有呼叫端送出的 request body 一個字都不變。
        forced_tool_name = None
        if tools:
            kwargs["tools"] = tools
            structured_tool = next((tool for tool in tools if tool.get("input_schema")), None)
            if structured_tool:
                forced_tool_name = structured_tool["name"]
                # Anthropic 官方 Tool use：client tool 用 input_schema 定義輸入；tool_choice=tool
                # 強制指定工具，回應參數位於 tool_use content block 的 input。
                # https://docs.claude.com/en/docs/agents-and-tools/tool-use/implement-tool-use
                kwargs["tool_choice"] = {"type": "tool", "name": forced_tool_name}

        # max_retries=0：重試歸 gateway 管，每次重試都是自己一列 llm_task（06 §11、本模組
        # gateway.py 開頭第 4 條）。SDK 預設會自己重試 2 次（DEFAULT_MAX_RETRIES，
        # anthropic/_constants.py:10），一次 complete() 因此變成最多 3 個 HTTP 請求：
        # timeout_s 實際上是 3×timeout_s（實測 llm_01M167R89MVG8F7JK6YCQWM1NW 設 120 秒卻
        # 跑了 361.58 秒），而那些被放棄、伺服器端卻已經產生的回應照樣計費，卻永遠不會寫進
        # llm_task.cost——每月花費上限加總的就是那個欄位（gateway.py run_task 開頭）。
        client = anthropic.Anthropic(api_key=api_key).with_options(timeout=timeout_s, max_retries=0)

        try:
            response = client.messages.create(**kwargs)
        except TypeError as exc:
            # 這個 SDK 版本在缺憑證時，是在送出請求當下才拋出 TypeError（訊息含
            # "authentication"／"api_key"），而不是在建構 client 時；兩種情況都轉成人話錯誤。
            message = str(exc).lower()
            if "authentication" in message or "api_key" in message:
                raise ProviderError(MISSING_KEY_MESSAGE) from exc
            raise
        except anthropic.RateLimitError as exc:
            raise ProviderError("AI 服務暫時無法回應（已達流量限制），請稍後再試。") from exc
        except anthropic.APIStatusError as exc:
            # 不把供應商原始回應（JSON、request id 等術語）帶進訊息——所有顯示這個
            # 錯誤的頁面（設定頁測試連線、建檔精靈錯誤 banner）都只給人話（§12）。
            lowered = str(exc).lower()
            if exc.status_code == 401 or "authentication" in lowered:
                human = "金鑰錯誤：AI 服務不接受這把金鑰。請確認複製時有沒有少字，或到 Anthropic 重新產生一把。"
            elif "credit" in lowered or "billing" in lowered:
                human = "餘額不足：金鑰是對的，但帳戶額度不夠。請先到 Anthropic 帳戶儲值再試。"
            else:
                human = f"AI 服務回應錯誤（狀態碼 {exc.status_code}），請稍後再試。"
            raise ProviderError(human) from exc
        except anthropic.APITimeoutError as exc:
            raise ProviderTimeoutError("AI 服務逾時未回應，請再試一次。") from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError("無法連線到 AI 服務，請檢查網路後再試一次。") from exc
        except anthropic.AnthropicError as exc:
            # 涵蓋建構 client 時就失敗的情況（例如未來 SDK 版本改為即時檢查憑證）。
            raise ProviderError(MISSING_KEY_MESSAGE) from exc

        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            suffix = f"（分類：{category}）" if category else ""
            raise ProviderError(f"模型婉拒本次請求{suffix}")

        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        structured = next(
            (block.input for block in response.content
             if getattr(block, "type", None) == "tool_use"
             and getattr(block, "name", None) == forced_tool_name
             and isinstance(getattr(block, "input", None), dict)),
            None,
        )
        # 網路搜尋結果（票 08）：官方回應形狀見 web_search_tool_result_block.py——
        # block.content 成功時是 list[WebSearchResultBlock]，出錯時是單一
        # WebSearchToolResultError（.error_code），一律先判斷型別再取值，出錯的區塊直接跳過，
        # 不索引、不拋例外（票 08 兩條不可妥協規則第 2 條）。
        search_sources = []
        for block in response.content:
            if getattr(block, "type", None) != "web_search_tool_result":
                continue
            content = getattr(block, "content", None)
            if not isinstance(content, list):
                continue  # WebSearchToolResultError：搜尋本身出錯，跳過這個區塊，不是例外
            for result in content:
                url = getattr(result, "url", None)
                if url:
                    search_sources.append({"title": getattr(result, "title", "") or "", "url": url})
        usage = response.usage
        # server_tool_use 只在真的用了伺服器端工具時才有值，沒開工具時是 None（ADR 0005）。
        server_tool_use = getattr(usage, "server_tool_use", None)
        return ProviderResponse(
            output_text=text,
            structured=structured,
            usage=Usage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
                web_search_requests=(
                    getattr(server_tool_use, "web_search_requests", 0) or 0
                ) if server_tool_use else 0,
            ),
            stop_reason=response.stop_reason,
            raw=response,
            search_sources=search_sources,
        )


_CODEX_IMAGE_EXTENSIONS = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp",
}


def _build_codex_prompt(system: str | None, messages: list) -> tuple:
    """多輪訊息攤平成一段 prompt（票 codex-cli-dev 規則 10）：system 原文放最前面，之後
    每則訊息加 [user]／[assistant] 標頭；不可以只送最後一則、把上下文丟掉。

    回傳 (prompt文字, 這次呼叫用到的 image content block 清單)。
    """
    parts = [system] if system else []
    image_blocks = []
    for message in messages:
        header = "[assistant]" if message.get("role") == "assistant" else "[user]"
        content = message.get("content")
        if isinstance(content, str):
            parts.append(f"{header}\n{content}")
            continue
        texts = []
        for block in content or []:
            block_type = block.get("type")
            if block_type == "text":
                texts.append(block.get("text", ""))
            elif block_type == "image":
                image_blocks.append(block)
        parts.append(f"{header}\n" + "\n".join(texts))
    return "\n\n".join(parts), image_blocks


def _write_codex_image(tmp_path: Path, index: int, block: dict) -> Path:
    """把 Anthropic base64 image block 解回暫存檔（票 codex-cli-dev 規則 9）；檔案跟著
    呼叫端的 TemporaryDirectory 一起清掉，不需要另外的 try/finally。"""
    source = block.get("source") or {}
    ext = _CODEX_IMAGE_EXTENSIONS.get(source.get("media_type", ""), ".bin")
    path = tmp_path / f"image_{index}{ext}"
    path.write_bytes(base64.b64decode(source.get("data", "")))
    return path


def _kill_codex_process_tree(proc: subprocess.Popen) -> None:
    """逾時後連子程序一起殺（codex 會再開 node）：Windows 沒有 os.killpg，用 taskkill
    /F /T 連整棵程序樹一起殺；其他平台 proc.kill() 只殺母行程（票 codex-cli-dev 規則 6）。
    """
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, text=True)
    else:
        proc.kill()


class CodexCliProvider:
    """本機 Codex CLI 線路（內部測試用，見本檔開頭 codex_cli_enabled 區塊）：實作跟
    AnthropicProvider 一樣的 Provider 介面，靠 select_provider() 換上，呼叫端完全不用改。

    - 隔離：--ignore-user-config 擋掉使用者 config.toml 的 plugins／MCP／memories；
      cwd 指向一個空的 TemporaryDirectory，不讓 codex 在專案目錄裡跑（同時也是暫存的
      輸出檔／schema 檔／圖片檔的家，離開 with 區塊自動清掉）。
    - 結構化輸出：tools 裡若有帶 input_schema 的工具（呼叫端原本要 Anthropic 強制呼叫
      該工具），改用 to_strict_schema() 轉換後的 --output-schema 逼模型輸出對應 JSON——
      CLI 沒有 tool_choice，沒辦法強制呼叫工具，因此改成直接約束最終輸出的形狀。
    - 網路搜尋：tools 裡有 WEB_SEARCH_TOOL 時加 -c tools.web_search=true；JSONL 裡
      web_search 這種 item.completed 事件的則數當作 usage.web_search_requests；
      search_sources 拿不到，固定回空清單（已知且接受的缺口，見票內容）。
    - 最終文字一律讀 -o 那個檔，不從 JSONL 的 agent_message 事件裡撿——模型可能先講一句
      「我要去搜尋了」才給答案，那些都不是最終文字。
    - 截斷偵測：CLI 沒有 max_tokens、也沒有 stop_reason，stop_reason 固定回 "end_turn"，
      本機模式偵測不到產出截斷，這是已知限制不是 bug。
    - cost 一律 0（見 app/llm/pricing.py 對 gpt-5.6-luna 的註記）。
    """

    name = "codex_cli"

    def complete(
        self,
        *,
        model: str,
        system: str | None,
        messages: list,
        max_tokens: int,
        timeout_s: float = 120.0,
        effort: str | None = None,
        tools: list | None = None,
        org_id: str | None = None,
    ) -> ProviderResponse:
        prompt, image_blocks = _build_codex_prompt(system, messages)

        structured_tool = next((tool for tool in (tools or []) if tool.get("input_schema")), None)
        web_search = any(tool == WEB_SEARCH_TOOL for tool in (tools or []))

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            output_file = tmp_path / "output.txt"
            image_paths = [_write_codex_image(tmp_path, i, b) for i, b in enumerate(image_blocks)]

            cmd = [
                "codex", "exec", "--ignore-user-config", "--skip-git-repo-check", "--ephemeral",
                "-s", "read-only", "-m", model, "--json", "-o", str(output_file),
            ]
            # 思考等級（ARCHITECTURE.md §1 rule 4）：codex CLI 沒有 max 檔，比照
            # resolve_thinking 的五檔對齊到 CLI 的 model_reasoning_effort；max 沒有對應
            # 選項所以摺到 xhigh（最高檔），None／不在表內一律不送、讓 CLI 用自己的預設。
            codex_effort = {"low": "low", "medium": "medium", "high": "high",
                             "xhigh": "xhigh", "max": "xhigh"}.get(effort)
            if codex_effort is not None:
                cmd += ["-c", f'model_reasoning_effort="{codex_effort}"']
            # 探測結果（票內容）：shell 工具開著時，3/10 次會在任務中途另外跑一次指令、
            # 把整段 prompt 重送一遍（17.5k → 40k input）；這條路線只需要文字任務，六個
            # 工具全關，不做事件或回合計數（§1 rule 4 說明為何不必）。
            cmd += [
                "--disable", "shell_tool", "--disable", "browser_use",
                "--disable", "computer_use", "--disable", "apps",
                "--disable", "image_generation", "--disable", "in_app_browser",
            ]
            if structured_tool is not None:
                schema_file = tmp_path / "schema.json"
                schema_file.write_text(
                    json.dumps(to_strict_schema(structured_tool["input_schema"]), ensure_ascii=False),
                    encoding="utf-8",
                )
                cmd += ["--output-schema", str(schema_file)]
            if web_search:
                cmd += ["-c", "tools.web_search=true"]
            for image_path in image_paths:
                cmd += ["-i", str(image_path)]
            cmd.append("-")

            proc = subprocess.Popen(
                cmd, cwd=tmpdir, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
            )
            try:
                stdout, stderr = proc.communicate(input=prompt, timeout=timeout_s)
            except subprocess.TimeoutExpired as exc:
                _kill_codex_process_tree(proc)
                proc.wait()
                raise ProviderTimeoutError("AI 服務（本機 Codex CLI）逾時未回應，請再試一次。") from exc

            events = []
            for line in stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except ValueError:
                    continue  # 非 JSON 的雜訊行（不應該出現，但不因此整段爆掉）

            for event in events:
                # 頂層 error／turn.failed 才是致命失敗；item.completed 底下型別為 error 的
                # 事件是非致命通知，規格明講必須忽略，不在這個迴圈的判斷範圍內。
                if event.get("type") in ("error", "turn.failed"):
                    # 兩種形狀：頂層 error 的訊息在 event["message"]，turn.failed 的在
                    # event["error"]["message"]（例如 schema 被退的 400 就只出現在後者）。
                    # 只讀前者的話，看的人會拿到一句沒有內容的「執行失敗」。
                    message = (event.get("message")
                               or (event.get("error") or {}).get("message")
                               or "本機 Codex CLI 執行失敗")
                    raise ProviderError(f"AI 服務（本機 Codex CLI）失敗：{message}")

            if proc.returncode != 0:
                raise ProviderError(
                    f"AI 服務（本機 Codex CLI）失敗（結束碼 {proc.returncode}）："
                    f"{stderr.strip() or '無詳細訊息'}"
                )
            if not output_file.exists():
                raise ProviderError("AI 服務（本機 Codex CLI）沒有產生輸出，請再試一次。")
            output_text = output_file.read_text(encoding="utf-8", errors="replace")

            web_search_requests = sum(
                1 for event in events
                if event.get("type") == "item.completed"
                and (event.get("item") or {}).get("type") == "web_search"
            )
            usage_event = next(
                (event.get("usage") or {} for event in events if event.get("type") == "turn.completed"),
                {},
            )

            structured = None
            if structured_tool is not None:
                try:
                    structured = json.loads(output_text)
                except ValueError:
                    structured = None

            return ProviderResponse(
                output_text=output_text,
                structured=structured,
                usage=Usage(
                    input_tokens=usage_event.get("input_tokens", 0) or 0,
                    output_tokens=usage_event.get("output_tokens", 0) or 0,
                    cache_read_input_tokens=usage_event.get("cached_input_tokens", 0) or 0,
                    cache_creation_input_tokens=usage_event.get("cache_write_input_tokens", 0) or 0,
                    web_search_requests=web_search_requests,
                ),
                stop_reason="end_turn",
                # reasoning_output_tokens 不確定是否已含在 output_tokens 內，不編、不併，
                # 原樣存在 raw 這個自由格式欄位裡（票 codex-cli-dev 規則 11）。
                raw=usage_event,
                search_sources=[],
            )


class ScriptedProvider:
    """罐頭回覆線路（e2e 後端專用，見本檔開頭 SCRIPTED_REPLIES 區塊）：實作跟 AnthropicProvider
    一樣的 Provider 介面，靠 select_provider() 換上。`structured` 一律回 None——每個呼叫端都是
    透過 gateway.parse_json_reply() 讀 rendered_output，走跟真實回覆一樣的解析路徑，不是抄捷徑
    直接塞 structured dict。"""

    name = "scripted"

    def __init__(self, reply: dict):
        self._reply = reply

    def complete(
        self,
        *,
        model: str,
        system: str | None,
        messages: list,
        max_tokens: int,
        timeout_s: float = 120.0,
        effort: str | None = None,
        tools: list | None = None,
        org_id: str | None = None,
    ) -> ProviderResponse:
        return ProviderResponse(
            output_text=json.dumps(self._reply, ensure_ascii=False),
            structured=None,
            usage=Usage(input_tokens=0, output_tokens=0),
            stop_reason="end_turn",
            search_sources=[],
        )


class FakeProvider:
    """測試用 Provider：不發任何真實網路請求，可注入預設回覆／例外。

    - response：每次呼叫回傳的 ProviderResponse（預設一個成功回應）。
    - exception：若指定，前 fail_first_n 次呼叫拋出這個例外；之後改回傳 response。
      fail_first_n=0（預設）代表每次呼叫都拋出（用於測試「全部嘗試皆失敗」）。
    - calls：記錄每次呼叫的參數，供測試斷言呼叫內容（含 effort，票 #27：思考等級解析後
      實際傳給 provider 的值，供路由層測試核對覆寫有沒有生效；含 tools，ADR 0005：
      呼叫端有沒有帶網路搜尋工具）。
    """

    name = "fake"

    def __init__(
        self,
        response: ProviderResponse | None = None,
        exception: Exception | None = None,
        fail_first_n: int = 0,
    ):
        self.response = response or ProviderResponse(
            output_text="（假回覆）測試用輸出",
            structured=None,
            usage=Usage(input_tokens=100, output_tokens=50),
            stop_reason="end_turn",
        )
        self.exception = exception
        self.fail_first_n = fail_first_n
        self.calls: list = []

    def complete(
        self,
        *,
        model: str,
        system: str | None,
        messages: list,
        max_tokens: int,
        timeout_s: float = 120.0,
        effort: str | None = None,
        tools: list | None = None,
        org_id: str | None = None,
    ) -> ProviderResponse:
        call_no = len(self.calls) + 1
        self.calls.append(
            {"model": model, "system": system, "messages": messages,
             "max_tokens": max_tokens, "timeout_s": timeout_s, "effort": effort,
             "tools": tools}
        )
        should_fail = self.exception is not None and (
            self.fail_first_n == 0 or call_no <= self.fail_first_n
        )
        if should_fail:
            raise self.exception
        return self.response
