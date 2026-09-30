"""app/intake/custom.py — 「自訂：用自己的話說」 of brand onboarding (F42-I05).

One plain-language sentence from the user → ONE small model call through `app/llm/gateway.py`
(task type `intake_custom`) → one field value or one new option for the block, contract-checked
here. Nothing is saved: the result is a proposal the screen shows checked, and the step's PUT
(下一步) saves it with everything else (F42 decision 「自訂 returns a proposal only」).

Input to the model is only the block's current option labels (capped) and the sentence (≤200
chars). The reply is read as JSON; each block reads only its own keys, so one reply shape can
serve every block (the e2e scripted reply relies on that). Any digit in the result must appear
in the user's sentence: the AI may reword, never add a number.

Entry point: `propose`, called by `app/intake/routes_onboarding_api.py`. F43 extends the block
set (product blocks) — the signature takes no product today.
"""

import re

from app.brand_intelligence import repository as bi_repo
from app.core import vocab
from app.core.db import Conn
from app.intake import onboarding, state
from app.intake import repository as ir
from app.llm import gateway, providers

# Tests swap this (same pattern as app/intake/ai.py).
PROVIDER = providers.AnthropicProvider()

TASK_TYPE = "intake_custom"
UNREADABLE = "custom_unreadable"  # the ValueError text of a contract failure (router: 422)
UNREADABLE_MESSAGE = "AI 整理不出來，換個說法再試一次"
COST_CUSTOM = 0.05  # estimate checked against the open draft's cost cap before the call
MAX_TOKENS = 600
MAX_INPUT_CHARS = 200
MAX_OPTIONS = 30
MAX_OPTION_CHARS = 20

MAX_POSITIONING_CHARS = 60
MAX_VISUAL_CHARS = onboarding.MAX_TEXT_CHARS
MAX_TONE_LABEL_CHARS = 8
MAX_PROOF_CHARS = onboarding.MAX_TEXT_CHARS
MAX_POLICY_LABEL_CHARS = 20
MAX_POLICY_SENTENCE_CHARS = 60
MAX_FORBIDDEN_CHARS = onboarding.MAX_FORBIDDEN_CHARS

_PROOF_LABELS = dict(vocab.PROOF_KINDS)

BLOCK_LABELS = {
    "positioning": "一句話說你的品牌",
    "tone": "說話的口氣",
    "visual": "畫面風格",
    "brand_proof": "品牌證據",
    "policy": "全店政策",
    "forbidden": "不能講的話",
}
BLOCKS = tuple(BLOCK_LABELS)


class CustomRefused(Exception):
    """The request is refused before (or instead of) a usable reply: bad input (400), the draft
    cost cap (409) or a failed model call (502, the gateway's human message)."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


_SYSTEM = (
    "你是品牌建檔助手，把使用者用自己的話說的一句話整理成指定欄位。只用使用者說的內容，"
    "不加他沒說的事實、數字或承諾。只回傳 JSON，不要任何 JSON 以外的文字。"
)


def _instruction(block: str) -> str:
    if block == "positioning":
        return (f"整理成品牌的一句話定位（給誰、解決什麼，最多 {MAX_POSITIONING_CHARS} 字）。"
                '只回傳 JSON：{"value": "…"}')
    if block == "visual":
        return (f"整理成廣告畫面風格的描述（色調、光線、場景，最多 {MAX_VISUAL_CHARS} 字）。"
                '只回傳 JSON：{"value": "…"}')
    if block == "tone":
        return (f"整理成一個說話口氣的名稱（最多 {MAX_TONE_LABEL_CHARS} 個字），"
                "不要跟已有的口氣重複。"
                '只回傳 JSON：{"label": "…"}')
    if block == "brand_proof":
        kinds = "；".join(f"{k}＝{label}" for k, label in vocab.PROOF_KINDS)
        return (f"判斷這是哪一種品牌證據（fact_key 只能用：{kinds}），並把內容整理成一句"
                f"（最多 {MAX_PROOF_CHARS} 字）。"
                '只回傳 JSON：{"fact_key": "…", "text": "…"}')
    if block == "policy":
        offers = "；".join(f"{k}＝{label}" for k, label in vocab.OFFER_LABELS.items())
        return (f"整理成一條店家的全店政策：label＝政策名稱（最多 {MAX_POLICY_LABEL_CHARS} 字）、"
                f"offer_key＝廣告裡會當成哪一種（只能用：{offers}；不是優惠就用 none）、"
                f"sentence＝廣告上會寫的那句話（最多 {MAX_POLICY_SENTENCE_CHARS} 字，"
                "只用使用者說的條件與數字）。"
                '只回傳 JSON：{"label": "…", "offer_key": "…", "sentence": "…"}')
    return (f"整理成一條廣告裡不能講的話（最多 {MAX_FORBIDDEN_CHARS} 字），不要跟已有的重複。"
            '只回傳 JSON：{"text": "…"}')


def _clean_options(options) -> list:
    out = []
    for option in options if isinstance(options, list) else []:
        label = str(option).strip()[:MAX_OPTION_CHARS]
        if label and label not in out:
            out.append(label)
        if len(out) >= MAX_OPTIONS:
            break
    return out


def _prompt(block: str, text: str, options: list) -> str:
    lines = [f"欄位：{BLOCK_LABELS[block]}"]
    if options:
        lines.append("已有的選項：" + "、".join(options))
    lines.append(f"使用者說：{text}")
    lines.append(_instruction(block))
    return "\n".join(lines)


_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _numbers(text: str) -> set:
    return set(_NUMBER.findall(text.replace(",", "").replace("，", "")))


def _text(data: dict, key: str, limit: int, source: str) -> str:
    value = data.get(key)
    value = value.strip() if isinstance(value, str) else ""
    if not value or len(value) > limit or not _numbers(value) <= _numbers(source):
        raise ValueError(UNREADABLE)
    return value


def check_reply(block: str, data, text: str) -> dict:
    """Program check of one block's reply contract -> the response. ValueError(UNREADABLE) on
    anything outside it (not an object, a missing/over-long field, a `fact_key`/`offer_key`
    outside its vocabulary, a number the user did not say)."""
    if block not in BLOCK_LABELS:
        raise ValueError(f"unknown block: {block}")
    if not isinstance(data, dict):
        raise ValueError(UNREADABLE)
    if block in ("positioning", "visual"):
        limit = MAX_POSITIONING_CHARS if block == "positioning" else MAX_VISUAL_CHARS
        return {"block": block, "kind": "value", "value": _text(data, "value", limit, text)}
    if block == "tone":
        option = {"label": _text(data, "label", MAX_TONE_LABEL_CHARS, text)}
    elif block == "brand_proof":
        fact_key = data.get("fact_key")
        if fact_key not in _PROOF_LABELS:
            raise ValueError(UNREADABLE)
        option = {"fact_key": fact_key, "label": _PROOF_LABELS[fact_key],
                  "text": _text(data, "text", MAX_PROOF_CHARS, text)}
    elif block == "policy":
        offer_key = data.get("offer_key")
        if not isinstance(offer_key, str) or offer_key not in vocab.OFFER_LABELS:
            raise ValueError(UNREADABLE)
        label = _text(data, "label", MAX_POLICY_LABEL_CHARS, text)
        option = {"key": vocab.CUSTOM_POLICY_KEY, "label": label, "offer_key": offer_key,
                  "offer_label": vocab.offer_label(offer_key),
                  "sentence": _text(data, "sentence", MAX_POLICY_SENTENCE_CHARS, text),
                  "params": {"label": label, "offer_key": offer_key}}
    else:
        option = {"text": _text(data, "text", MAX_FORBIDDEN_CHARS, text)}
    return {"block": block, "kind": "option", "option": option}


def propose(conn: Conn, brand_id: str, block: str, text: str, context: dict | None = None) -> dict:
    """One sentence → one proposal for `block` (see `check_reply` for the shapes). `context`
    optional `{"options": [labels]}` overrides the block's current options read from the brand.
    Raises CustomRefused (400/409/502) or ValueError(UNREADABLE) (422); writes no brand data."""
    if block not in BLOCK_LABELS:
        raise CustomRefused(400, "不認得要自訂的區塊。")
    text = str(text or "").strip()
    if not text:
        raise CustomRefused(400, "先用一句話說說看。")
    if len(text) > MAX_INPUT_CHARS:
        raise CustomRefused(400, f"一句話就好，最多 {MAX_INPUT_CHARS} 字。")
    options = (context or {}).get("options")
    options = _clean_options(options if options is not None
                             else onboarding.custom_options(conn, brand_id, block))
    draft = state.get_draft(brand_id, conn)
    if draft is not None and state.would_exceed(draft, COST_CUSTOM):
        raise CustomRefused(409, f"這次建檔的 AI 用量已到上限（US$ {draft['cost_spent']:.2f}／"
                                 f"US$ {draft['budget_limit']:.2f}），這一格請直接自己填。")
    brand = bi_repo.get_brand(conn, brand_id) or {}
    scope = {"brand_id": brand_id, "block": block}
    if draft is not None:
        scope["intake_draft_id"] = draft["id"]
    task = gateway.run_task(
        conn, PROVIDER, brand_id=brand_id, task_type=TASK_TYPE,
        prompt_template_id=TASK_TYPE, prompt_template_version="v1", system=_SYSTEM,
        messages=[{"role": "user", "content": _prompt(block, text, options)}],
        context=gateway.TaskContext(context_scope=scope, knowledge_item_ids=[],
                                    brand_version=brand.get("knowledge_version") or 1),
        options=gateway.TaskOptions(max_tokens=MAX_TOKENS, max_retries=0),
    )
    if draft is not None:
        ir.add_llm_task_ref(conn, brand_id, draft["id"], task["id"], f"自訂：{BLOCK_LABELS[block]}")
    if task["status"] != "succeeded":
        raise CustomRefused(502, task["error"] or UNREADABLE_MESSAGE)
    return check_reply(block, gateway.parse_json_reply(task["rendered_output"]), text)
