"""app/intake/product_prefill.py — product onboarding 「✦ AI 從商品頁讀到」 (F43-I06).

The product-page read that pre-fills `#/p1`–`#/p4` of product onboarding: ONE gateway call
(task type `intake_product_prefill`) with the product page's text (`net.read_url`, one page) and
up to three product photos already uploaded (image blocks). No web search. The reply is
contract-checked entry by entry here (an invalid entry is dropped, the rest kept) and stored in
`intake_product_prefill` as a proposal — never a confirmed fact: each step's PUT confirms it
(`app/intake/product_onboarding.py` shows it while the step is not saved yet).

Same rules as the brand prefill (`app/intake/ai.py` `run_prefill`, whose note / proof checks are
reused): a source note naming something this read did not read is invented and its entry dropped;
an unreadable reply fails the job with `ai.PARSE_FAIL_MESSAGE`; a failed call fails it with the
gateway's own error. Customer quotes must be verbatim from the page: a quote that is not on the
page (whitespace ignored) is blanked, unless the group's note names a photo that was read.

Queued as `background.intake_product_prefill` (lock per product, `prefill_lock`) by
`start_on_create` (product creation with a page URL) and `start_scan` (`POST …/onboarding/scan`,
the explicit re-read). The AI cost cap refuses before anything is queued: the brand's shared AI
spend cap (`app.core.settings.budget_exceeded_message`, the same cap the legacy product research
and the ads module check), because a product is usually built after the brand's onboarding draft
is closed.

Row states: `running` (queued) → `done` (`prefill_json` = the checked proposal + `pages_read` /
`photos_read`) or `failed` (`prefill_json = {"error": 〈人話〉}`).

Tests swap `PROVIDER` and `read_url` (same pattern as `app/intake/ai.py`).
"""

import json
import logging

from app import storage
from app.brand_intelligence import background_job
from app.brand_intelligence import repository as bi_repo
from app.core import interrupts as core_interrupts
from app.core import net, vocab
from app.core import settings as coresettings
from app.core.db import Conn, new_id
from app.core.db import connection as core_db_connection
from app.intake import ai
from app.intake import product_onboarding as po
from app.intake import repository as ir
from app.llm import gateway, providers
from app.shared.web import app_path

_log = logging.getLogger(__name__)

# Tests swap these (same pattern as app/intake/ai.py).
PROVIDER = providers.AnthropicProvider()
read_url = net.read_url

TASK_TYPE = "intake_product_prefill"
TASK_NAME = "background.intake_product_prefill"
COST_PREFILL = ai.COST_PREFILL  # same estimate as the brand read (one page + photos, one call)
MAX_TOKENS = 4000
MAX_PHOTOS = 3
MAX_CLAIMS = 8
MAX_SELL_WAYS = 4
NOTHING_READ_MESSAGE = (
    "讀不到商品頁（網址打不開或沒有文字），也沒有商品照；可以重試，或直接自己填。"
)


def nothing_read_message(reason: str | None) -> str:
    """The failed read's sentence, naming `read_url`'s reason when a page was tried (Contract F);
    no page URL at all keeps the generic sentence."""
    if not reason:
        return NOTHING_READ_MESSAGE
    return f"讀不到商品頁（{reason}），也沒有商品照；可以改網址再重試，或直接自己填。"

_KEYS = ("intro", "mechanism", "difference", "groups", "proof", "claims", "sell_ways")
_TEXT_LIMITS = {key: limit for key, _fact, _label, limit in po.WHAT_FIELDS}
_PAIN_LABELS = dict(vocab.PAIN_KINDS)


class ScanRefused(Exception):
    """The AI cost cap refuses the read before it is queued (router: 409)."""


def prefill_lock(product_id: str) -> str:
    """Queueing lock of the product prefill job (one per product)."""
    return f"intake_product_prefill:{product_id}"


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM = (
    "你是商品建檔助手。只根據這次提供的商品頁文字與商品照片整理資料，"
    "不用自己的知識補、不猜、不上網查。只回傳 JSON，不要任何 JSON 以外的文字。"
)


def _prompt(product_name: str, page: tuple | None, photos: int) -> str:
    lines = [f"商品名稱：{product_name}"]
    if page is not None:
        lines.append(f"【商品頁】{page[0]}\n{page[1]}")
    lines.append("【來源目錄】\n" + json.dumps(
        ai.prefill_sources([page] if page else [], label="商品頁"), ensure_ascii=False))
    if photos:
        lines.append(f"附上的商品照片共 {photos} 張。")
    pains = "；".join(f"{k}＝{label}" for k, label in vocab.PAIN_KINDS)
    kinds = "；".join(f"{k}＝{label}" for k, label in vocab.PROOF_KINDS)
    lines.append(f"六種煩惱（pain_key＝名稱）：{pains}")
    lines.append(f"證據種類（fact_key＝名稱）：{kinds}")
    lines.append(
        "規則：\n"
        "1. 每一項必須帶 source_refs，格式為"
        '[{"source_id":"page:1","quote":"來源原文片段"}]。source_id 只能用來源目錄的 ID，'
        "quote 必須逐字引用該來源。找不到引文就不要列；來源標籤由程式產生，不填 note。"
        "顧客群詮釋可以改寫，但仍要有引用，仍只是提議。照片沒有獨立文字或 OCR，"
        "不可自行造照片引文；來源存在不等於內容、功效或廣告資格已查證。\n"
        f"2. intro：一句話介紹這個商品（最多 {_TEXT_LIMITS['intro']} 字）；"
        f"mechanism：裡面有什麼、怎麼作用（最多 {_TEXT_LIMITS['mechanism']} 字）；"
        f"difference：跟別家不一樣的地方（最多 {_TEXT_LIMITS['difference']} 字）。"
        "沒寫就不要填。\n"
        f"3. groups：看得出來的顧客群，最多 {po.MAX_GROUPS} 群。who＝是誰；"
        f"pain_keys＝他們買之前最煩的事，只能從六種煩惱挑 1～{po.MAX_PAINS} 個 key；"
        "quote＝顧客自己說的話，必須是頁面上逐字照抄的原話（例如評論），"
        "沒有就留空字串，不要自己寫；when_used＝什麼時候用，沒寫就留空字串。\n"
        "4. proof：頁面或照片上寫明的證據，fact_key 只能用上面的證據種類。\n"
        "5. claims：頁面上對這個商品的說法（功效、成分、保證等），逐句照抄，"
        f"最多 {MAX_CLAIMS} 句；不用判斷能不能講。\n"
        f"6. sell_ways：頁面上寫明的賣法，最多 {MAX_SELL_WAYS} 種："
        "name＝賣法名稱（例如「單盒」「三盒組」），qty＝一次買幾件（整數），"
        "price＝售價，list_price＝頁面寫的原價，沒寫就 null。"
        "數字只能用頁面上寫的，不要換算、不要推測。\n"
        "7. 沒寫的就不要填，不要用推測補。\n"
        '每個非空項目均加上 source_refs。只回傳 JSON：{"intro": {"value": "…", "source_refs": []}, '
        '"mechanism": {"value": "…", "source_refs": []}, '
        '"difference": {"value": "…", "source_refs": []}, '
        '"groups": [{"who": "…", "pain_keys": ["…"], "quote": "", "when_used": "", '
        '"source_refs": []}], '
        '"proof": [{"fact_key": "…", "text": "…", "source_refs": []}], '
        '"claims": [{"text": "…", "source_refs": []}], '
        '"sell_ways": [{"name": "…", "qty": 1, "price": 0, "list_price": null, '
        '"source_refs": []}]}'
    )
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Contract check
# ---------------------------------------------------------------------------

def _check_texts(data: dict, note_of) -> tuple[dict, int]:
    out, dropped = {}, 0
    for key in ("intro", "mechanism", "difference"):
        item = data.get(key)
        if item is None:
            continue
        if not isinstance(item, dict):
            dropped += 1
            continue
        value = ai._clean_text(item.get("value"), _TEXT_LIMITS[key])
        note = note_of(item)
        if value is None or note is None:
            dropped += 1
            continue
        out[key] = {"value": value, "note": note}
    return out, dropped


def _optional_text(value, limit: int) -> str | None:
    """"" when absent; None when not a string or over `limit`."""
    if value is None:
        return ""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text if len(text) <= limit else None


def _check_groups(items, note_of, page_text: str) -> tuple[list, int]:
    """≤3 groups; pain keys outside the six are dropped (and repeats), more than two cut to two; a
    group left without a pain key, without 是誰 or with an invented note is dropped. A quote not
    found verbatim on the page is blanked; images are not independently quoted text."""
    groups, seen, dropped = [], set(), 0
    page = ai.normalized_quote(page_text)
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or len(groups) >= po.MAX_GROUPS:
            dropped += 1
            continue
        raw = item.get("pain_keys")
        raw = raw if isinstance(raw, list) else []
        pains = list(dict.fromkeys(k for k in raw if isinstance(k, str) and k in _PAIN_LABELS))
        dropped += len(raw) - len(pains) + max(0, len(pains) - po.MAX_PAINS)
        pains = pains[: po.MAX_PAINS]
        who = ai._clean_text(item.get("who"), po.MAX_WHO_CHARS)
        quote = _optional_text(item.get("quote"), po.MAX_QUOTE_CHARS)
        when_used = _optional_text(item.get("when_used"), po.MAX_WHEN_CHARS)
        note = note_of(item)
        if (not pains or who is None or who in seen or note is None
                or quote is None or when_used is None):
            dropped += 1
            continue
        if quote and not (ai.normalized_quote(quote) and ai.normalized_quote(quote) in page):
            quote, dropped = "", dropped + 1  # not the page's own words: never an invented quote
        seen.add(who)
        groups.append({"who": who, "pain_keys": pains, "quote": quote,
                       "when_used": when_used, "note": note})
    return groups, dropped


def _check_claims(items, note_of) -> tuple[list, int]:
    claims, seen, dropped = [], set(), 0
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            dropped += 1
            continue
        text = ai._clean_text(item.get("text"), po.MAX_CLAIM_CHARS)
        note = note_of(item)
        if text is None or note is None or text in seen or len(claims) >= MAX_CLAIMS:
            dropped += 1
            continue
        seen.add(text)
        claims.append({"text": text, "note": note})
    return claims, dropped


def _money(value) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    return value


def _check_sell_ways(items, note_of) -> tuple[list, int]:
    """≤4; name within the name limit, qty a positive integer, price > 0. A list price that is not
    a number above the price is not kept (null) — the entry stays."""
    ways, seen, dropped = [], set(), 0
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or len(ways) >= MAX_SELL_WAYS:
            dropped += 1
            continue
        name = ai._clean_text(item.get("name"), po.MAX_NAME_CHARS)
        qty, price = item.get("qty"), _money(item.get("price"))
        note = note_of(item)
        if (name is None or name.casefold() in seen or isinstance(qty, bool)
                or not isinstance(qty, int) or qty <= 0 or price is None or note is None):
            dropped += 1
            continue
        list_price = _money(item.get("list_price"))
        if list_price is not None and list_price <= price:
            list_price = None
        seen.add(name.casefold())
        ways.append({"name": name, "qty": qty, "price": price, "list_price": list_price,
                     "note": note})
    return ways, dropped


def validate_reply(data, *, page_text: str, pages_read: int,
                   photos_read: int, sources: list[ai.PrefillSource] | None = None) -> tuple[dict | None, int]:
    """Program check of the product prefill reply -> (prefill, dropped entry count). `None` =
    unreadable (not an object, or none of the contract's keys). Every entry is checked on its own;
    notes are generated from quoted references to this call's fetched text catalog."""
    if not isinstance(data, dict) or not any(key in data for key in _KEYS):
        return None, 0

    def note_of(item: dict) -> str | None:
        return ai.source_note(item, sources or [])

    out, dropped = _check_texts(data, note_of)
    out["groups"], n = _check_groups(data.get("groups"), note_of, page_text)
    dropped += n
    out["proof"], n = ai._check_proof(data.get("proof"), note_of)
    dropped += n
    out["claims"], n = _check_claims(data.get("claims"), note_of)
    dropped += n
    out["sell_ways"], n = _check_sell_ways(data.get("sell_ways"), note_of)
    dropped += n
    return out, dropped


# ---------------------------------------------------------------------------
# The call
# ---------------------------------------------------------------------------


def _photo_blocks(conn: Conn, brand: dict, product_id: str) -> list:
    """Up to `MAX_PHOTOS` of the product's photos (oldest first) as image blocks; a photo that
    cannot be read or has an unsupported format is skipped (not counted as read)."""
    blocks = []
    for asset in po.product_photo_assets(conn, brand["id"]):
        if len(blocks) >= MAX_PHOTOS:
            break
        if asset["product_id"] != product_id:
            continue
        try:
            content, content_type = storage.get(org_id=brand["org_id"], key=asset["storage_key"])
            blocks.append(providers.base64_image_block(content_type, content))
        except (storage.StorageError, ValueError, KeyError):
            continue
    return blocks


def _fail(conn: Conn, brand_id: str, product_id: str, message: str, task_id: str | None = None):
    ir.save_product_prefill(conn, brand_id, product_id, status="failed",
                            prefill_json={"error": message}, llm_task_id=task_id)
    return False, message


def run_prefill(conn: Conn, brand_id: str, product_id: str) -> tuple:
    """Read the product page and ≤3 product photos in ONE call and store the checked proposal
    (`done`). (True, None) on success; (False, 人話) after storing `failed` — the call failed, the
    reply is unreadable, or nothing could be read (no call then)."""
    brand = bi_repo.get_brand(conn, brand_id) or {}
    product = po.knowledge_product(conn, brand_id, product_id)
    page, reason = None, None
    if product.get("page_url"):
        ok, text, reason = read_url(product["page_url"])
        if ok and text and text.strip():
            page = (product["page_url"], text.strip())
        else:
            reason = reason or net.REASON_EMPTY
    blocks = _photo_blocks(conn, brand, product_id)
    if page is None and not blocks:
        return _fail(conn, brand_id, product_id, nothing_read_message(reason))
    prompt = {"type": "text", "text": _prompt(product["name"], page, len(blocks))}
    task = gateway.run_task(
        conn, PROVIDER, brand_id=brand_id, task_type=TASK_TYPE,
        prompt_template_id=TASK_TYPE, prompt_template_version="v1", system=_SYSTEM,
        messages=[{"role": "user", "content": [*blocks, prompt]}],
        context=gateway.TaskContext(
            context_scope={"brand_id": brand_id, "product_id": product_id},
            knowledge_item_ids=[],  # the product has no confirmed knowledge yet
            brand_version=brand.get("knowledge_version") or 1,
        ),
        options=gateway.TaskOptions(max_tokens=MAX_TOKENS),
    )
    if task["status"] != "succeeded":
        return _fail(conn, brand_id, product_id, task["error"] or ai.PARSE_FAIL_MESSAGE, task["id"])
    prefill, dropped = validate_reply(
        gateway.parse_json_reply(task["rendered_output"]), page_text=page[1] if page else "",
        pages_read=1 if page else 0, photos_read=len(blocks),
        sources=ai.prefill_sources([page] if page else [], label="商品頁"))
    if prefill is None:
        return _fail(conn, brand_id, product_id, ai.PARSE_FAIL_MESSAGE, task["id"])
    if dropped:
        _log.info("intake product prefill %s: dropped %d invalid entries", task["id"], dropped)
    prefill.update(pages_read=1 if page else 0, photos_read=len(blocks))
    ir.save_product_prefill(conn, brand_id, product_id, status="done", prefill_json=prefill,
                            llm_task_id=task["id"])
    return True, None


# ---------------------------------------------------------------------------
# Queue: start (creation / re-read), status, the background task
# ---------------------------------------------------------------------------


def _cost_refusal(conn: Conn, brand: dict) -> str | None:
    return coresettings.budget_exceeded_message(
        conn, brand["id"], COST_PREFILL, org_id=brand["org_id"], action="AI 讀商品頁",
        fallback_hint="或直接自己填。")


def _queue(conn: Conn, brand: dict, product_id: str) -> None:
    from app.background import enqueue, is_active

    lock = prefill_lock(product_id)
    ir.save_product_prefill(conn, brand["id"], product_id, status="running")
    if not is_active(lock):
        enqueue(TASK_NAME, org_id=brand["org_id"], lock=lock, brand_id=brand["id"],
                product_id=product_id)


def start_on_create(conn: Conn, brand_id: str, product_id: str) -> None:
    """A new product with a page URL: queue the read; the cost cap's refusal is stored as the
    read's failure (the product is still created; the step shows the message and 自己填)."""
    brand = bi_repo.get_brand(conn, brand_id) or {}
    refusal = _cost_refusal(conn, brand)
    if refusal:
        ir.save_product_prefill(conn, brand_id, product_id, status="failed",
                                prefill_json={"error": refusal})
        return
    _queue(conn, brand, product_id)


def start_scan(conn: Conn, brand_id: str, product_id: str, *, page_url=None,
               actor: str = "") -> dict:
    """`POST …/products/{p}/onboarding/scan` `{page_url?}`: read the product page again -> the
    onboarding status. A `page_url` sent with the retry is stored on the product first, so the
    read is of the address the user just typed (Contract F). No-op while a read runs. NotFound:
    not this brand's product; ValueError: the product is finished (proposals are no longer
    shown), the URL is not one, or there is neither a page URL nor a photo; ScanRefused: the AI
    cost cap (checked before anything is queued, so no call is made)."""
    from app.background import is_active

    product = po.knowledge_product(conn, brand_id, product_id)
    if product.get("onboarding_step") is None:
        raise ValueError("這個商品已經建檔完成，不需要再讀一次商品頁；要改請直接改各步。")
    if page_url is not None:
        po.set_page_url(conn, brand_id, product_id, page_url, actor=actor)
        product = po.knowledge_product(conn, brand_id, product_id)
    photos = [a for a in po.product_photo_assets(conn, brand_id) if a["product_id"] == product_id]
    if not product.get("page_url") and not photos:
        raise ValueError("還沒有商品頁網址或商品照，AI 沒有東西可以讀；可以直接自己填。")
    if is_active(prefill_lock(product_id)):
        return po.status(conn, brand_id, product_id)
    brand = bi_repo.get_brand(conn, brand_id) or {}
    refusal = _cost_refusal(conn, brand)
    if refusal:
        raise ScanRefused(refusal)
    _queue(conn, brand, product_id)
    return po.status(conn, brand_id, product_id)


def running_status(product_id: str) -> tuple[str, str | None]:
    """A `running` row: running while its job is queued / processing; failed with the queue's
    message once the newest job ended without writing the row (Contract J)."""
    from app.background import JOB_FAILED_MESSAGE, is_active, job_outcome

    lock = prefill_lock(product_id)
    outcome = job_outcome(lock)
    if outcome == "active" or (outcome is None and is_active(lock)):
        return "running", None
    return "failed", JOB_FAILED_MESSAGE


def background_intake_product_prefill(org_id: str, brand_id: str, product_id: str) -> None:
    """The queued product-page read. A product deleted meanwhile ends quietly; any other failure
    is stored on the row, notified, then re-raised so the job ends failed (Contract J)."""
    from app.background import JOB_FAILED_MESSAGE

    with core_db_connection() as conn:
        product = bi_repo.get_product(conn, brand_id, product_id)
        if product is None:
            return
        error = None
        try:
            ok, message = run_prefill(conn, brand_id, product_id)
            if not ok:
                error = RuntimeError(message)
        except Exception as exc:  # noqa: BLE001 — store + notify first, then re-raise
            conn.rollback()
            error = exc
            _fail(conn, brand_id, product_id, JOB_FAILED_MESSAGE)
        background_job.notify(
            conn, brand_id, category="intake_ai_step_done", dedupe_key=new_id("itkjob"),
            message=core_interrupts.notice(
                "AI 讀完商品頁，可以回去確認" if error is None
                else "商品頁沒讀成，可以重試或自己填",
                product["name"]),
            action_url=app_path(f"/brands/{brand_id}/products/{product_id}/onboarding"),
        )
        if error is not None:
            raise error
