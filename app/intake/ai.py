"""app/intake/ai.py — 品牌建檔的真實 LLM 呼叫：F42-I05「AI 讀網站與品牌照片預填」`run_prefill`
（「自訂」在 app/intake/custom.py）。舊階段的初掃印象／照片產品卡／下一題／貼回格式修復已由
F42-I14 拆掉。

全部經 app/llm/gateway.run_task 進出（寫 llm_task、算成本、失敗重試一次），呼叫後
把 llm_task_id 記進草稿的 llm_task_refs_json——花費累計即時 SUM llm_task.cost，
不存副本（03 §3A.5 第 5 點）。

無金鑰時 AnthropicProvider 在打出網路請求前就拋人話錯誤（07 §3），gateway 把它記成
失敗列；本檔一律回傳 (ok, 人話錯誤訊息)，路由層據此顯示錯誤與「前往設定頁」引導，
不當機、不假裝成功（principles 16 誠實狀態）。

測試／煙霧測試把模組層 PROVIDER 換成 FakeProvider、read_url 換成假抓取（回 (ok, 文字, 原因)），
不發任何真實網路請求。
"""

import json
import logging
import unicodedata
from typing import TypedDict

from app import storage
from app.brand_intelligence import repository as bi_repo
from app.core import input_rules, net, vocab
from app.intake import onboarding
from app.intake import repository as ir
from app.llm import gateway, providers

_log = logging.getLogger(__name__)

# 測試可整個換掉（跟 app/tests 既有 FakeProvider 風格一致）
PROVIDER = providers.AnthropicProvider()

# 綁成本模組的名字，測試才能只換這裡（實作已移到 app/core/net.py，產品調研也要用）
read_url = net.read_url
# Not read by the prefill any more (it needs the reason: `read_url`); kept because legacy tests
# (app/tests/test_intake.py) still swap this name in setUp.
fetch_url = net.fetch_url

PARSE_FAIL_MESSAGE = "AI 有回覆，但格式讀不成預期的樣子。可以再試一次。"

_parse_json_reply = gateway.parse_json_reply  # 搬到 gateway.py 公開，這裡留別名（行為零變化）


def _run(conn, draft: dict, *, task_type: str, purpose: str, system: str, user_text: str,
         options: gateway.TaskOptions = None, content_blocks: list = None) -> dict:
    brand_id = draft["brand_id"]
    row = conn.execute("SELECT knowledge_version FROM brand WHERE id = %s", (brand_id,)).fetchone()
    context = gateway.TaskContext(
        context_scope={"brand_id": brand_id, "intake_draft_id": draft["id"]},
        knowledge_item_ids=[],  # 建檔階段：品牌還沒有已確認的知識可組
        brand_version=row["knowledge_version"] if row else 1,
    )
    task = gateway.run_task(
        conn, PROVIDER, brand_id=brand_id, task_type=task_type,
        prompt_template_id=task_type, prompt_template_version="v1",
        system=system,
        messages=[{"role": "user", "content": content_blocks if content_blocks is not None else user_text}],
        context=context,
        options=options,
    )
    ir.add_llm_task_ref(conn, brand_id, draft["id"], task["id"], purpose)
    return task


# ---------------------------------------------------------------------------
# Brand onboarding prefill (F42-I05): one call reads the draft's website pages and brand
# photos and proposes what steps 3/4 (#/b3, #/b4) show with an 「AI 讀到」 tag. The reply is
# contract-checked entry by entry here; the result is a proposal in `intake_draft.prefill_json`,
# never a confirmed fact (the step's 下一步 confirms it).
# ---------------------------------------------------------------------------

PREFILL_TASK_TYPE = "intake_prefill"
PREFILL_PURPOSE = "AI 讀網站與品牌照片預填"  # llm_task_refs_json purpose: how the status finds its call
COST_PREFILL = 0.30  # estimate checked against the draft cost cap before the job is queued
PREFILL_MAX_TOKENS = 4000
MAX_PREFILL_PAGES = onboarding.MAX_URLS
MAX_PREFILL_PHOTOS = 5
MAX_POSITIONING_CHARS = 60
MAX_VISUAL_CHARS = onboarding.MAX_TEXT_CHARS
MAX_PROOF_CHARS = onboarding.MAX_TEXT_CHARS
MAX_PREFILL_PRODUCTS = 20
MAX_PRODUCT_NAME_CHARS = 40
MAX_NOTE_CHARS = 40
MAX_POLICY_PARAM_CHARS = 60

# What the scan may report as 「沒找到」 (display labels, in the prototype's step order).
AREA_POSITIONING, AREA_TONE, AREA_VISUAL = "一句話定位", "說話的口氣", "畫面風格"
AREA_POLICIES, AREA_PRODUCTS = "全店政策", "可能的商品"
PREFILL_AREAS = (AREA_POSITIONING, AREA_TONE, AREA_VISUAL,
                 *(label for _, label in vocab.PROOF_KINDS), AREA_POLICIES, AREA_PRODUCTS)
_PREFILL_KEYS = ("positioning", "tone", "visual", "proof", "policies", "products", "not_found")
_PROOF_LABELS = dict(vocab.PROOF_KINDS)


def prefill_lock(brand_id: str) -> str:
    """Queueing lock of the prefill job (task `background.intake_scan` with `prefill=True`)."""
    return f"intake_prefill:{brand_id}"


_PREFILL_SYSTEM = (
    "你是品牌建檔助手。只根據這次提供的網站頁面文字與品牌照片整理資料，"
    "不用自己的知識補、不猜、不上網查。只回傳 JSON，不要任何 JSON 以外的文字。"
)


def _policy_menu() -> str:
    rows = []
    for p in vocab.POLICY_TYPES:
        params = "、".join(f"{q['name']}（{q['label']}）" for q in p["params"])
        rows.append(f"{p['key']}＝{p['label']}" + (f"：{params}" if params else ""))
    return "；".join(rows)


def _prefill_prompt(brand_name: str, pages: list, photo_kinds: list) -> str:
    lines = [f"品牌名稱：{brand_name}"]
    for index, (url, text) in enumerate(pages, start=1):
        lines.append(f"【頁面 {index}】{url}\n{text}")
    lines.append("【來源目錄】\n" + json.dumps(prefill_sources(pages), ensure_ascii=False))
    if photo_kinds:
        lines.append("附上的品牌照片依序是：" + "、".join(
            f"第 {i} 張＝{kind}" for i, kind in enumerate(photo_kinds, start=1)))
    lines.append("可選的說話口氣：" + "、".join(vocab.TONES))
    lines.append("證據種類（fact_key＝名稱）：" + "；".join(f"{k}＝{label}" for k, label in vocab.PROOF_KINDS))
    lines.append("全店政策（key＝名稱：參數）：" + _policy_menu())
    lines.append("「沒找到」只能從這些面向挑：" + "、".join(PREFILL_AREAS))
    lines.append(
        "規則：\n"
        "1. 每一項（包含商品與顧客群詮釋）必須帶 source_refs，格式為"
        '[{"source_id":"page:1","quote":"來源原文片段"}]。source_id 只能用來源目錄的 ID，'
        "quote 必須逐字引用該來源。找不到引文就不要列；來源標籤由程式產生，不填 note。"
        "照片沒有獨立文字或 OCR，不可自行造照片引文。引用只表示來源出現，並非查證內容為真。\n"
        f"2. positioning：一句話說這個品牌是給誰、解決什麼（最多 {MAX_POSITIONING_CHARS} 字）。\n"
        "3. tone：從可選的說話口氣挑 1～2 個。visual：畫面風格（色調、光線、場景）。\n"
        "4. proof：網站或照片上寫明的證據，fact_key 只能用上面的證據種類。\n"
        "5. policies：網站上寫明的全店政策，key 只能用上面的清單，params 只填網站寫明的數字或文字，"
        "沒寫就不要填那個參數；清單裡沒有的政策不要列。\n"
        f"6. products：實際看到的商品名稱（最多 {MAX_PREFILL_PRODUCTS} 個），url 是該商品頁網址，"
        "不知道就 null；不要列價格。\n"
        "7. 沒找到的面向列進 not_found；沒有就不要填，不要用推測補。\n"
        '每個非空項目均加上 source_refs。只回傳 JSON：{"positioning": {"value": "…", "source_refs": []}, '
        '"tone": {"values": ["…"], "source_refs": []}, "visual": {"value": "…", "source_refs": []}, '
        '"proof": [{"fact_key": "…", "text": "…", "source_refs": []}], '
        '"policies": [{"key": "…", "params": {"參數": "值"}, "source_refs": []}], '
        '"products": [{"name": "…", "url": null, "source_refs": []}], "not_found": ["面向"]}'
    )
    return "\n\n".join(lines)


def _clean_text(value, limit: int) -> str | None:
    """A non-empty string within `limit` chars, else None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text if text and len(text) <= limit else None


class PrefillSource(TypedDict):
    source_id: str
    url: str
    text: str
    note: str


def prefill_sources(pages: list, *, label: str = "頁面") -> list[PrefillSource]:
    """The fetched text catalog; image blocks have no independently quoted text/OCR."""
    return [{"source_id": f"page:{index}", "url": url, "text": text,
             "note": f"頁面 {index}" if label == "頁面" else label}
            for index, (url, text) in enumerate(pages, start=1)]


def normalized_quote(text: str) -> str:
    """Normalize width and whitespace, without inventing text or checking its truth."""
    return "".join(unicodedata.normalize("NFKC", text).split()).strip("「」『』“”\"'")


def source_note(item: dict, sources: list[PrefillSource]) -> str | None:
    """All quoted references must match this call's catalog; model-written notes are ignored.
    Matching proves source presence, not a proposition's truth or advertising eligibility."""
    refs = item.get("source_refs")
    if not isinstance(refs, list) or not refs:
        return None
    catalog = {source["source_id"]: source for source in sources}
    notes = []
    for ref in refs:
        if not isinstance(ref, dict) or not isinstance(ref.get("source_id"), str):
            return None
        source = catalog.get(ref["source_id"])
        quote = ref.get("quote")
        if source is None or not isinstance(quote, str):
            return None
        span = normalized_quote(quote)
        if not span or span not in normalized_quote(source["text"]):
            return None
        notes.append(source["note"])
    return "、".join(dict.fromkeys(notes))


def _clean_policy_params(key: str, raw) -> dict | None:
    """Only the registry's own param names with a scalar value; None = params not an object."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        return None
    names = {p["name"] for p in vocab.POLICY_TYPES_BY_KEY[key]["params"]}
    out = {}
    for name, value in raw.items():
        if name not in names or isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (int, float)):
            out[name] = value
        elif isinstance(value, str) and value.strip() and len(value.strip()) <= MAX_POLICY_PARAM_CHARS:
            out[name] = value.strip()
    return out


def _check_value_blocks(data: dict, note_of) -> tuple[dict, int]:
    out, dropped = {}, 0
    for key, limit in (("positioning", MAX_POSITIONING_CHARS), ("visual", MAX_VISUAL_CHARS)):
        item = data.get(key)
        if item is None:
            continue
        value = _clean_text(item.get("value"), limit) if isinstance(item, dict) else None
        note = note_of(item) if isinstance(item, dict) else None
        if value is None or note is None:
            dropped += 1
            continue
        out[key] = {"value": value, "note": note}
    return out, dropped


def _check_tone(tone, note_of) -> tuple[dict | None, int]:
    if tone is None:
        return None, 0
    raw = tone.get("values") if isinstance(tone, dict) else None
    raw = raw if isinstance(raw, list) else []
    values = list(dict.fromkeys(v for v in raw if isinstance(v, str) and v in vocab.TONES))
    dropped = len(raw) - len(values)  # outside TONES, or a repeat
    if len(values) > onboarding.TONE_MAX:
        dropped += len(values) - onboarding.TONE_MAX
        values = values[:onboarding.TONE_MAX]
    note = note_of(tone) if isinstance(tone, dict) else None
    if not values or note is None:
        return None, dropped + (1 if values or not raw else 0)
    return {"values": values, "note": note}, dropped


def _check_proof(items, note_of) -> tuple[list, int]:
    proof, seen, dropped = [], set(), 0
    for item in items if isinstance(items, list) else []:
        fact_key = item.get("fact_key") if isinstance(item, dict) else None
        text = _clean_text(item.get("text"), MAX_PROOF_CHARS) if isinstance(item, dict) else None
        note = note_of(item) if isinstance(item, dict) else None
        if fact_key not in _PROOF_LABELS or text is None or note is None or (fact_key, text) in seen:
            dropped += 1
            continue
        seen.add((fact_key, text))
        proof.append({"fact_key": fact_key, "text": text, "note": note})
    return proof, dropped


def _check_policies(items, note_of) -> tuple[list, int]:
    policies, seen, dropped = [], set(), 0
    for item in items if isinstance(items, list) else []:
        key = item.get("key") if isinstance(item, dict) else None
        if not isinstance(key, str) or key not in vocab.POLICY_TYPES_BY_KEY or key in seen:
            dropped += 1
            continue
        params = _clean_policy_params(key, item.get("params"))
        note = note_of(item)
        if params is None or note is None:
            dropped += 1
            continue
        seen.add(key)
        policies.append({"key": key, "params": params, "note": note})
    return policies, dropped


def _check_products(items, note_of) -> tuple[list, int]:
    products, seen, dropped = [], set(), 0
    for item in items if isinstance(items, list) else []:
        name = _clean_text(item.get("name"), MAX_PRODUCT_NAME_CHARS) if isinstance(item, dict) else None
        note = note_of(item) if isinstance(item, dict) else None
        if name is None or note is None or name in seen or len(products) >= MAX_PREFILL_PRODUCTS:
            dropped += 1
            continue
        seen.add(name)
        try:  # a product page the model read: kept only when it is a full URL (input_rules.url)
            url = input_rules.url(item.get("url"), "商品頁網址", optional=True)
        except input_rules.InputRuleError:
            url = None
        products.append({"name": name, "url": url, "note": note})
    return products, dropped


def found_areas(prefill: dict) -> set:
    """The `PREFILL_AREAS` a checked prefill has something for."""
    found = {AREA_POSITIONING} if prefill.get("positioning") else set()
    found |= {AREA_TONE} if prefill.get("tone") else set()
    found |= {AREA_VISUAL} if prefill.get("visual") else set()
    found |= {_PROOF_LABELS[p["fact_key"]] for p in prefill.get("proof") or []}
    found |= {AREA_POLICIES} if prefill.get("policies") else set()
    found |= {AREA_PRODUCTS} if prefill.get("products") else set()
    return found


def validate_prefill_reply(data, *, pages_read: int, photos_read: int,
                           sources: list[PrefillSource] | None = None) -> tuple[dict | None, int]:
    """Program check of the prefill reply contract -> (prefill, dropped entry count).
    `None` = unreadable (not an object, or none of the contract's keys). Every entry is checked on
    its own: an invalid one (a tone outside `TONES`, an unknown proof/policy key, over-long text, a
    source this scan did not read, …) is dropped and counted; the rest is kept."""
    if not isinstance(data, dict) or not any(key in data for key in _PREFILL_KEYS):
        return None, 0

    def note_of(item: dict) -> str | None:
        return source_note(item, sources or [])

    out, dropped = _check_value_blocks(data, note_of)
    tone, n = _check_tone(data.get("tone"), note_of)
    dropped += n
    if tone is not None:
        out["tone"] = tone
    out["proof"], n = _check_proof(data.get("proof"), note_of)
    dropped += n
    out["policies"], n = _check_policies(data.get("policies"), note_of)
    dropped += n
    out["products"], n = _check_products(data.get("products"), note_of)
    dropped += n
    found = found_areas(out)
    raw_missing = data.get("not_found") if isinstance(data.get("not_found"), list) else []
    out["not_found"] = [a for a in dict.fromkeys(raw_missing) if a in PREFILL_AREAS and a not in found]
    dropped += len(raw_missing) - len(out["not_found"])
    return out, dropped


def _read_pages(urls: list) -> tuple[list, list]:
    """-> (pages read as (url, text), pages not read as {url, reason}); the reason is
    `read_url`'s short Chinese sentence (HTTP status, timeout, unknown domain, certificate, empty
    page; Contract F)."""
    pages, failed = [], []
    for url in urls[:MAX_PREFILL_PAGES]:
        ok, text, reason = read_url(url)
        if ok and text and text.strip():
            pages.append((url, text.strip()))
        else:
            failed.append({"url": url, "reason": reason or net.REASON_EMPTY})
    return pages, failed


def _brand_photo_blocks(conn, brand_id: str) -> tuple[list, list]:
    """Up to `MAX_PREFILL_PHOTOS` brand photos as image content blocks + their kind labels. A
    photo that cannot be read or has an unsupported format is skipped (not counted as read)."""
    brand = bi_repo.get_brand(conn, brand_id) or {}
    blocks, kinds = [], []
    for asset in onboarding.brand_photo_assets(conn, brand_id):
        if len(blocks) >= MAX_PREFILL_PHOTOS:
            break
        try:
            content, content_type = storage.get(org_id=brand["org_id"], key=asset["storage_key"])
            blocks.append(providers.base64_image_block(content_type, content))
        except (storage.StorageError, ValueError, KeyError):
            continue
        kinds.append(vocab.asset_kind_label(asset["asset_kind"]))
    return blocks, kinds


def empty_prefill() -> dict:
    return {"proof": [], "policies": [], "products": [], "not_found": [],
            "pages_read": 0, "photos_read": 0, "urls_read": [], "pages_failed": []}


def run_prefill(conn, draft: dict) -> tuple:
    """Read the draft's website pages (≤5) and brand photos (≤5) and send them in ONE call; store
    the checked proposal in `intake_draft.prefill_json` with `pages_read`/`photos_read`, the URL
    list this read was for (`urls_read`) and the pages it could not read (`pages_failed`,
    Contract F). (True, None) on success; (False, 人話錯誤) when the call failed or the reply is
    unreadable. Nothing readable (every page failed, no photo): no call, an empty prefill that read
    0/0. The product suggestions the user dismissed (`dismissed`) survive a new read."""
    brand_id = draft["brand_id"]
    urls = list(draft["urls"])[:MAX_PREFILL_PAGES]
    pages, failed = _read_pages(urls)
    blocks, kinds = _brand_photo_blocks(conn, brand_id)
    previous = (ir.get_draft(conn, brand_id, draft["id"]) or {}).get("prefill_json")
    kept: dict = {"urls_read": urls, "pages_failed": failed}
    if isinstance(previous, dict) and previous.get("dismissed"):
        kept["dismissed"] = previous["dismissed"]
    if not pages and not blocks:
        ir.update_draft(conn, brand_id, draft["id"], prefill_json={**empty_prefill(), **kept})
        return True, None
    text = {"type": "text", "text": _prefill_prompt(draft["brand_name"], pages, kinds)}
    task = _run(conn, draft, task_type=PREFILL_TASK_TYPE, purpose=PREFILL_PURPOSE,
                system=_PREFILL_SYSTEM, user_text="", content_blocks=[*blocks, text],
                options=gateway.TaskOptions(max_tokens=PREFILL_MAX_TOKENS))
    if task["status"] != "succeeded":
        return False, task["error"]
    prefill, dropped = validate_prefill_reply(
        _parse_json_reply(task["rendered_output"]), pages_read=len(pages), photos_read=len(blocks),
        sources=prefill_sources(pages))
    if prefill is None:
        return False, PARSE_FAIL_MESSAGE
    if dropped:
        _log.info("intake prefill %s: dropped %d invalid entries", task["id"], dropped)
    prefill.update(pages_read=len(pages), photos_read=len(blocks), **kept)
    ir.update_draft(conn, brand_id, draft["id"], prefill_json=prefill)
    return True, None


def prefill_failure_message(conn, draft_row: dict) -> str:
    """What a failed prefill job shows: its last model call's own error; a call that succeeded
    means the reply was unreadable; no call at all = the queue's generic message."""
    from app.background import JOB_FAILED_MESSAGE

    refs = [r for r in draft_row.get("llm_task_refs_json") or [] if r.get("purpose") == PREFILL_PURPOSE]
    task = gateway.get_task(conn, refs[-1]["llm_task_id"]) if refs else None
    if task is None:
        return JOB_FAILED_MESSAGE
    if task["status"] == "succeeded":
        return PARSE_FAIL_MESSAGE
    return task["error"] or JOB_FAILED_MESSAGE
