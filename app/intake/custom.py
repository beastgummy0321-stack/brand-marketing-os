"""app/intake/custom.py — 「自訂：用自己的話說」 of brand onboarding (F42-I05) and product
onboarding (F43-I06).

One plain-language sentence from the user → ONE small model call through `app/llm/gateway.py`
(task type `intake_custom`) → one field value or one new option for the block, contract-checked
here. Nothing is saved: the result is a proposal the screen shows checked, and the step's PUT
(下一步) saves it with everything else (F42 decision 「自訂 returns a proposal only」).

Input to the model is only the block's current option labels (capped) and the sentence (≤200
chars). The reply is read as JSON; each block reads only its own keys, so one reply shape can
serve every block (the e2e scripted reply relies on that). Any digit in the result must appear
in the user's sentence: the AI may reword, never add a number.

Product blocks (F43-I06, `product_id` given): difference → value; group → `{who, pain_keys, quote,
when_used}`; pain → `{pain_key, label, quote}` (a worry mapped to one of the six); product_proof →
`{fact_key, label, text}`; claim → `{text, verdict: ok|no, statutory}` — a 食安法 hit (brand
regime, `product_onboarding.statutory_flag`) is attached as `statutory`, a reminder only; the
verdict is never rewritten (F48 decision 13). The cost cap of a
product block is the brand's shared AI spend cap (as the product-page read, `product_prefill`).

Entry point: `propose`, called by `app/intake/routes_onboarding_api.py` (brand blocks) and
`app/intake/routes_product_api.py` (product blocks, `product_id=`).
"""

import re

from app.brand_intelligence import repository as bi_repo
from app.core import settings as coresettings
from app.core import vocab
from app.core.db import Conn
from app.intake import onboarding, state
from app.intake import product_onboarding as po
from app.intake import repository as ir
from app.llm import gateway, providers

# Tests swap this (same pattern as app/intake/ai.py).
PROVIDER = providers.AnthropicProvider()

TASK_TYPE = "intake_custom"
UNREADABLE = "custom_unreadable"  # the ValueError text of a contract failure (router: 422)
UNREADABLE_MESSAGE = "AI 整理不出來，換個說法再試一次"
COST_CUSTOM = 0.05  # estimate checked against the cost cap before the call
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

# Product onboarding blocks (F43-I06): `propose(..., product_id=...)` only.
PRODUCT_BLOCK_LABELS = {
    "difference": "跟別人不一樣的地方",
    "group": "誰會買（一群顧客）",
    "pain": "買之前最煩的事",
    "product_proof": "這個商品的證據",
    "claim": "這個商品的說法",
}
PRODUCT_BLOCKS = tuple(PRODUCT_BLOCK_LABELS)
_LABELS = {**BLOCK_LABELS, **PRODUCT_BLOCK_LABELS}
_DIFFERENCE_CHARS = next(limit for key, _f, _l, limit in po.WHAT_FIELDS if key == "difference")
_PAIN_LABELS = dict(vocab.PAIN_KINDS)
_VERDICTS = ("ok", "no")


class CustomRefused(Exception):
    """The request is refused before (or instead of) a usable reply: bad input (400), the cost
    cap (409) or a failed model call (502, the gateway's human message)."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


_SYSTEM = (
    "你是品牌建檔助手，把使用者用自己的話說的一句話整理成指定欄位。只用使用者說的內容，"
    "不加他沒說的事實、數字或承諾。只回傳 JSON，不要任何 JSON 以外的文字。"
)


def _pain_menu() -> str:
    return "；".join(f"{k}＝{label}" for k, label in vocab.PAIN_KINDS)


def _product_instruction(block: str) -> str:
    if block == "difference":
        return (f"整理成這個商品跟別家不一樣的地方（最多 {_DIFFERENCE_CHARS} 字）。"
                '只回傳 JSON：{"value": "…"}')
    if block == "group":
        return (f"整理成一群會買的顧客：who＝是誰（最多 {po.MAX_WHO_CHARS} 字）；"
                f"pain_keys＝他們買之前最煩的事，從這些挑 1～{po.MAX_PAINS} 個 key"
                f"（{_pain_menu()}）；"
                f"quote＝使用者說的顧客原話（最多 {po.MAX_QUOTE_CHARS} 字，沒說就空字串）；"
                f"when_used＝什麼時候用（最多 {po.MAX_WHEN_CHARS} 字，沒說就空字串）。"
                "不要跟已有的顧客群重複。"
                '只回傳 JSON：{"who": "…", "pain_keys": ["…"], "quote": "", "when_used": ""}')
    if block == "pain":
        return (f"把這個煩惱對到一種（pain_key 只能用：{_pain_menu()}），"
                f"quote＝用顧客的口吻把這個煩惱寫成一句話（最多 {po.MAX_QUOTE_CHARS} 字）。"
                '只回傳 JSON：{"pain_key": "…", "quote": "…"}')
    if block == "product_proof":
        kinds = "；".join(f"{k}＝{label}" for k, label in vocab.PROOF_KINDS)
        return (f"判斷這是哪一種商品證據（fact_key 只能用：{kinds}），並把內容整理成一句"
                f"（最多 {po.MAX_PROOF_CHARS} 字）。"
                '只回傳 JSON：{"fact_key": "…", "text": "…"}')
    return (f"整理成一句這個商品的說法（最多 {po.MAX_CLAIM_CHARS} 字），不要跟已有的說法重複；"
            "verdict＝使用者要不要在廣告裡講這句：可以講用 ok，不能講用 no。"
            '只回傳 JSON：{"text": "…", "verdict": "ok"}')


def _instruction(block: str) -> str:
    if block in PRODUCT_BLOCK_LABELS:
        return _product_instruction(block)
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
    lines = [f"欄位：{_LABELS[block]}"]
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


def _optional(data: dict, key: str, limit: int, source: str) -> str:
    """An optional text field: absent / empty = ""; otherwise the `_text` rules."""
    value = data.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        return ""
    return _text(data, key, limit, source)


def _pain_keys(value) -> list:
    if not isinstance(value, list):
        raise ValueError(UNREADABLE)
    keys = list(dict.fromkeys(value))
    if not 1 <= len(keys) <= po.MAX_PAINS or any(k not in _PAIN_LABELS for k in keys):
        raise ValueError(UNREADABLE)
    return keys


def _check_product_reply(block: str, data: dict, text: str) -> dict:
    if block == "difference":
        return {"block": block, "kind": "value",
                "value": _text(data, "value", _DIFFERENCE_CHARS, text)}
    if block == "group":
        option = {"who": _text(data, "who", po.MAX_WHO_CHARS, text),
                  "pain_keys": _pain_keys(data.get("pain_keys")),
                  "quote": _optional(data, "quote", po.MAX_QUOTE_CHARS, text),
                  "when_used": _optional(data, "when_used", po.MAX_WHEN_CHARS, text)}
    elif block == "pain":
        pain_key = data.get("pain_key")
        if not isinstance(pain_key, str) or pain_key not in _PAIN_LABELS:
            raise ValueError(UNREADABLE)
        option = {"pain_key": pain_key, "label": _PAIN_LABELS[pain_key],
                  "quote": _text(data, "quote", po.MAX_QUOTE_CHARS, text)}
    elif block == "product_proof":
        fact_key = data.get("fact_key")
        if fact_key not in _PROOF_LABELS:
            raise ValueError(UNREADABLE)
        option = {"fact_key": fact_key, "label": _PROOF_LABELS[fact_key],
                  "text": _text(data, "text", po.MAX_PROOF_CHARS, text)}
    else:
        verdict = data.get("verdict")
        if verdict not in _VERDICTS:
            raise ValueError(UNREADABLE)
        option = {"text": _text(data, "text", po.MAX_CLAIM_CHARS, text), "verdict": verdict,
                  "statutory": None}
    return {"block": block, "kind": "option", "option": option}


def check_reply(block: str, data, text: str) -> dict:
    """Program check of one block's reply contract -> the response. ValueError(UNREADABLE) on
    anything outside it (not an object, a missing/over-long field, a `fact_key`/`offer_key`/
    `pain_key`/`verdict` outside its vocabulary, a number the user did not say). A claim's
    食安法 flag needs the brand: `propose` sets it (and forces `no`)."""
    if block not in _LABELS:
        raise ValueError(f"unknown block: {block}")
    if not isinstance(data, dict):
        raise ValueError(UNREADABLE)
    if block in PRODUCT_BLOCK_LABELS:
        return _check_product_reply(block, data, text)
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


def _cap_refusal(conn: Conn, brand: dict, draft: dict | None, product_id: str | None) -> str | None:
    """Brand blocks: the open draft's cap (F42). Product blocks: the brand's shared AI spend cap
    (`budget_exceeded_message`, as the product-page read) — a product is usually built after the
    brand's draft is closed."""
    if product_id is not None:
        return coresettings.budget_exceeded_message(
            conn, brand["id"], COST_CUSTOM, org_id=brand["org_id"], action="這次自訂",
            fallback_hint="這一格也可以直接自己填。")
    if draft is not None and state.would_exceed(draft, COST_CUSTOM):
        return (f"這次建檔的 AI 用量已到上限（US$ {draft['cost_spent']:.2f}／"
                f"US$ {draft['budget_limit']:.2f}），這一格請直接自己填。")
    return None


def propose(conn: Conn, brand_id: str, block: str, text: str, context: dict | None = None, *,
            product_id: str | None = None) -> dict:
    """One sentence → one proposal for `block` (see `check_reply` for the shapes). Brand blocks
    without `product_id`, product blocks with it (the product must be this brand's knowledge
    product: `product_onboarding.NotFound` otherwise, router 404). `context` optional
    `{"options": [labels]}` overrides the block's current options read from the store.
    Raises CustomRefused (400/409/502) or ValueError(UNREADABLE) (422); writes no brand data."""
    labels = PRODUCT_BLOCK_LABELS if product_id is not None else BLOCK_LABELS
    if block not in labels:
        raise CustomRefused(400, "不認得要自訂的區塊。")
    text = str(text or "").strip()
    if not text:
        raise CustomRefused(400, "先用一句話說說看。")
    if len(text) > MAX_INPUT_CHARS:
        raise CustomRefused(400, f"一句話就好，最多 {MAX_INPUT_CHARS} 字。")
    options = (context or {}).get("options")
    if options is None:
        options = (po.custom_options(conn, brand_id, product_id, block) if product_id is not None
                   else onboarding.custom_options(conn, brand_id, block))
    elif product_id is not None:
        po.knowledge_product(conn, brand_id, product_id)  # NotFound before any call
    options = _clean_options(options)
    draft = state.get_draft(brand_id, conn) if product_id is None else None
    brand = bi_repo.get_brand(conn, brand_id) or {}
    refusal = _cap_refusal(conn, brand, draft, product_id)
    if refusal:
        raise CustomRefused(409, refusal)
    scope = {"brand_id": brand_id, "block": block}
    if draft is not None:
        scope["intake_draft_id"] = draft["id"]
    if product_id is not None:
        scope["product_id"] = product_id
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
    result = check_reply(block, gateway.parse_json_reply(task["rendered_output"]), text)
    if block == "claim":
        # F48 decision 13: the 食安法 hit rides along as a flag; the verdict is the model's
        # reading of the user's sentence and is never rewritten.
        option = result["option"]
        option["statutory"] = po.statutory_flag(conn, brand, option["text"])
    return result
