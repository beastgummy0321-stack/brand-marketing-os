"""app/intake/onboarding.py — brand onboarding (F42-I04): what each of the seven steps reads and
writes (`#/b1`–`#/b7` of `.harness/scratch/prototype/f41-onboarding/index.html`).

Every confirmed value lives in the store the F42 Decisions name and is written through the
`app.brand_intelligence.repository` facade (no SQL on its tables here). The AI scan's proposal
(`intake_draft.prefill_json`, written by F42-I05) is only read: a step shows it (`source="ai"`)
while that step has not been confirmed on an open draft; once the step's PUT ran (the draft's
`current_step` moved past it) or the brand is completed, only confirmed values are shown.

A brand without an open draft (completed, or never had one — e.g. the seed brand) is in
re-entry mode: the same GET/PUT read and write the stores directly.

Validation failures raise `ValueError` with a Chinese message; the router turns it into 400.

Entry points: the functions below, called only by `app/intake/routes_onboarding_api.py`.
"""

import json
from pathlib import Path

from app.brand_intelligence import repository as bi_repo
from app.core import vocab
from app.core.db import Conn
from app.intake import repository as ir
from app.intake import state

(STEP_BASICS, STEP_SCAN, STEP_IDENTITY, STEP_EVIDENCE, STEP_MEDIA, STEP_TOOLS,
 STEP_DONE) = range(1, 8)

MAX_URLS = 5
BRAND_PHOTO_KINDS = ("logo", "store", "team", "brand_image", "other")
TONE_MIN, TONE_MAX = 1, 2
MAX_TONE_CHARS = 20
MAX_TEXT_CHARS = 200
MAX_FORBIDDEN_CHARS = 50

# Display label of `brand.regulatory_regime`
# (value set: app/brand_intelligence/regulatory_regime.py).
REGIME_LABELS = {"food_tw": "台灣食品（食安法）"}

_CATALOGUE_FILE = Path(__file__).with_name("connector_catalogue.json")


# ---------------------------------------------------------------------------
# Draft context
# ---------------------------------------------------------------------------

def _open_draft(conn: Conn, brand_id: str) -> dict | None:
    return ir.get_active_draft(conn, brand_id)


def _draft_row(conn: Conn, brand_id: str) -> dict | None:
    """The open draft, else the latest completed one (None: the brand never had a draft)."""
    return ir.get_active_draft(conn, brand_id) or ir.get_latest_completed_draft(conn, brand_id)


def _prefill(conn: Conn, brand_id: str, step: int) -> dict:
    """The scan's proposal for `step`: only on an open draft whose step is not confirmed yet."""
    row = _open_draft(conn, brand_id)
    if row is None or row["current_step"] > step:
        return {}
    value = row.get("prefill_json")
    return value if isinstance(value, dict) else {}


def advance(conn: Conn, brand_id: str, step: int) -> None:
    """A step's PUT on an open draft moves `current_step` to at least step+1 (never back)."""
    row = _open_draft(conn, brand_id)
    if row is not None and row["current_step"] < step + 1:
        ir.update_draft(conn, brand_id, row["id"], current_step=step + 1)


def _prefill_status(row: dict | None, brand_id: str, is_open: bool) -> tuple[str, str | None]:
    if row is not None and row.get("prefill_json") is not None:
        return "done", None
    if not is_open:
        return "none", None
    from app.background import JOB_FAILED_MESSAGE, job_outcome

    outcome = job_outcome(f"intake_scan:{brand_id}")
    if outcome == "active":
        return "running", None
    if outcome == "failed":
        return "failed", JOB_FAILED_MESSAGE
    return "none", None


def status(conn: Conn, brand_id: str) -> dict:
    """`GET …/onboarding`: where the brand is in the seven steps."""
    open_row = _open_draft(conn, brand_id)
    row = open_row or ir.get_latest_completed_draft(conn, brand_id)
    has_scan_input = bool(row and (row.get("research_urls_json") or row.get("photos_json")))
    prefill_status, prefill_error = _prefill_status(row, brand_id, open_row is not None)
    return {
        "step": open_row["current_step"] if open_row else STEP_DONE,
        "completed": open_row is None,
        "skipped_scan": not has_scan_input,
        "prefill_status": prefill_status,
        "prefill_error": prefill_error,
    }


def complete(conn: Conn, brand_id: str) -> dict:
    """`POST …/onboarding/complete`: idempotent."""
    row = _open_draft(conn, brand_id)
    if row is not None:
        ir.complete_draft(conn, brand_id, row["id"])
    return status(conn, brand_id)


# ---------------------------------------------------------------------------
# Step 1 基本
# ---------------------------------------------------------------------------

def _photo_url(brand_id: str, asset: dict) -> str:
    # Served by the existing asset-file route (app/brand_web/routes.py `asset_file`).
    return f"/brands/{brand_id}/assets/file/{asset['id']}/{Path(asset['storage_key']).name}"


def brand_photos(conn: Conn, brand_id: str) -> list:
    """Brand photos = active official assets without a product, of a brand-photo kind."""
    assets = [a for a in bi_repo.list_official_assets(conn, brand_id)
              if a.get("product_id") is None and a.get("status") == "active"
              and a["asset_kind"] in BRAND_PHOTO_KINDS]
    assets.sort(key=lambda a: (a["created_at"], a["id"]))
    return [{"id": a["id"], "kind": a["asset_kind"], "url": _photo_url(brand_id, a)}
            for a in assets]


def check_photo_kinds(kinds: list, count: int) -> list:
    """`photo_kinds` parallel to `photo_tokens`; missing/empty → other; unknown → ValueError."""
    out = []
    for i in range(count):
        kind = str(kinds[i]).strip() if i < len(kinds) else ""
        kind = kind or "other"
        if kind not in BRAND_PHOTO_KINDS:
            raise ValueError(f"不認得的照片種類：{kind}")
        out.append(kind)
    return out


def check_urls(urls: list) -> list:
    urls = [str(u).strip() for u in urls if str(u).strip()]
    if len(urls) > MAX_URLS:
        raise ValueError(f"品牌網站最多 {MAX_URLS} 個。")
    bad = state.invalid_url(urls)
    if bad:
        raise ValueError(f"「{bad}」不是有效的網址，請以 https:// 或 http:// 開頭。")
    return urls


def check_market_region(value) -> str | None:
    value = str(value or "").strip()
    if value and value not in dict(vocab.MARKET_REGIONS):
        raise ValueError("請選擇有效的投放地區。")
    return value or None


def check_regime(value) -> str | None:
    value = str(value or "").strip()
    if value and value not in REGIME_LABELS:
        raise ValueError("請選擇有效的適用法規。")
    return value or None


def resolve_photos(tokens: list, kinds: list) -> list:
    """Resolve uploaded `photo_tokens` (validate `photo_kinds` first: resolving consumes the
    tokens) -> the uploaded photos, each with its `kind`. Unknown tokens are skipped."""
    tokens = [str(t) for t in tokens]
    kind_by_token = dict(zip(tokens, check_photo_kinds(kinds, len(tokens)), strict=True))
    return [{**p, "kind": kind_by_token[p["token"]]} for p in state.resolve_photo_tokens(tokens)]


def save_new_photos(conn: Conn, brand_id: str, photos: list, *, actor: str) -> None:
    """Each uploaded photo (from `resolve_photos`) becomes a brand-level official asset."""
    for photo in photos:
        bi_repo.create_official_asset(conn, brand_id, actor=actor, asset_kind=photo["kind"],
                                      storage_key=photo["storage_key"], title=photo.get("name"))


def get_basics(conn: Conn, brand_id: str) -> dict:
    brand = bi_repo.get_brand(conn, brand_id) or {}
    row = _draft_row(conn, brand_id)
    return {
        "name": brand.get("name") or "",
        "urls": list((row or {}).get("research_urls_json") or []),
        "photos": brand_photos(conn, brand_id),
        "market_region": brand.get("market_region"),
        "regulatory_regime": brand.get("regulatory_regime"),
        "advertising_history": brand.get("advertising_history"),
        "client_name": brand.get("client_name") or "",
        "description": (row or {}).get("description") or "",
    }


def put_basics(conn: Conn, brand_id: str, body: dict, *, actor: str) -> dict:
    """Edit of step 1 (re-entry). New photos: `body.photo_tokens` from the existing upload +
    parallel `body.photo_kinds`; `body.photo_ids` (optional) = the existing brand photos to keep
    (absent = keep all)."""
    name = str(body.get("name") or "").strip()
    if not name:
        raise ValueError("請填寫品牌名稱。")
    client_name = str(body.get("client_name") or "").strip() or None
    description = str(body.get("description") or "").strip()
    urls = check_urls(_list(body.get("urls")))
    market_region = check_market_region(body.get("market_region"))
    regime = check_regime(body.get("regulatory_regime"))
    history = body.get("advertising_history")
    if history is not None and history not in ("has_history", "none"):
        raise ValueError("請選擇是否曾經投放過網路廣告。")
    tokens = _list(body.get("photo_tokens"))
    kinds = _list(body.get("photo_kinds"))
    check_photo_kinds(kinds, len(tokens))
    keep_ids = body.get("photo_ids")
    current_photos = brand_photos(conn, brand_id)
    if keep_ids is not None:
        keep_ids = {str(i) for i in _list(keep_ids)}
        unknown = keep_ids - {p["id"] for p in current_photos}
        if unknown:
            raise ValueError("找不到要保留的品牌照片。")

    brand = bi_repo.get_brand(conn, brand_id) or {}
    if (brand.get("name"), brand.get("client_name")) != (name, client_name):
        bi_repo.update_brand(conn, brand_id, name=name, client_name=client_name,
                             status=brand.get("status") or "active", actor=actor)
    if brand.get("market_region") != market_region:
        bi_repo.set_brand_switches(conn, brand_id, market_region=market_region,
                                   conversion_goal=brand.get("conversion_goal"), actor=actor)
    if brand.get("regulatory_regime") != regime:
        bi_repo.set_regulatory_regime(conn, brand_id, regime, actor=actor)
    if history is not None and brand.get("advertising_history") != history:
        bi_repo.set_advertising_history(conn, brand_id, history, actor=actor)
    if keep_ids is not None:
        for photo in current_photos:
            if photo["id"] not in keep_ids:
                bi_repo.delete_official_asset(conn, brand_id, photo["id"], actor=actor)
    photos = resolve_photos(tokens, kinds)
    save_new_photos(conn, brand_id, photos, actor=actor)

    row = _draft_row(conn, brand_id)
    if row is None:  # a brand that never had a draft: keep its website list in a completed one
        row = ir.create_draft(conn, brand_id, description, [], urls, actor)
        ir.complete_draft(conn, brand_id, row["id"])
    draft_photos = list(row.get("photos_json") or []) + [
        {"storage_key": p["storage_key"], "display_name": p.get("name"),
         "size_bytes": int(round((p.get("size_mb") or 0) * 1024 * 1024)),
         "token": p.get("token") or ""} for p in photos]
    ir.update_draft(conn, brand_id, row["id"], description=description,
                    research_urls_json=urls, photos_json=draft_photos)
    advance(conn, brand_id, STEP_BASICS)
    return get_basics(conn, brand_id)


def _list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


# ---------------------------------------------------------------------------
# Step 3 品牌是誰
# ---------------------------------------------------------------------------

def _confirmed_facts(conn: Conn, brand_id: str, fact_type: str) -> list:
    return [f for f in bi_repo.list_brand_facts(conn, brand_id, status="confirmed")
            if f["fact_type"] == fact_type]


def _latest_fact(conn: Conn, brand_id: str, fact_type: str) -> dict | None:
    rows = _confirmed_facts(conn, brand_id, fact_type)
    return rows[-1] if rows else None


def _fact_tones(fact: dict) -> list:
    """The tones of a saved `tone` fact: `params_json.tones` (written by `put_identity`); a row
    without it (saved before F42-I04, or last edited in the library's fact form, which clears
    it) falls back to its value split on 「、」."""
    tones = (fact.get("params_json") or {}).get("tones")
    if isinstance(tones, list):
        return [str(t) for t in tones if str(t).strip()]
    return [t.strip() for t in str(fact.get("value") or "").split("、")
            if t.strip() and len(t.strip()) <= MAX_TONE_CHARS]


def _ai_block(prefill: dict, key: str) -> dict:
    block = prefill.get(key)
    return block if isinstance(block, dict) else {}


def _text_field(saved: dict | None, ai: dict) -> dict:
    if saved is not None:
        return {"value": saved["value"], "source": "saved", "note": ""}
    value = str(ai.get("value") or "").strip()
    if value:
        return {"value": value, "source": "ai", "note": str(ai.get("note") or "")}
    return {"value": "", "source": "none", "note": ""}


def get_identity(conn: Conn, brand_id: str) -> dict:
    prefill = _prefill(conn, brand_id, STEP_IDENTITY)
    tone_fact = _latest_fact(conn, brand_id, "tone")
    saved_tones = _fact_tones(tone_fact) if tone_fact else []
    ai_tone = _ai_block(prefill, "tone")
    ai_values = [str(t) for t in (ai_tone.get("values") or []) if str(t).strip()]
    if tone_fact is not None:
        tone = {"values": saved_tones, "source": "saved", "note": ""}
    elif ai_values:
        tone = {"values": ai_values[:TONE_MAX], "source": "ai",
                "note": str(ai_tone.get("note") or "")}
    else:
        tone = {"values": [], "source": "none", "note": ""}
    tone["options"] = list(vocab.TONES) + [t for t in saved_tones if t not in vocab.TONES]
    visual = _text_field(_latest_fact(conn, brand_id, "visual_base"), _ai_block(prefill, "visual"))
    visual["photo_urls"] = [p["url"] for p in brand_photos(conn, brand_id)]
    return {
        "positioning": _text_field(_latest_fact(conn, brand_id, "positioning"),
                                   _ai_block(prefill, "positioning")),
        "tone": tone,
        "visual": visual,
    }


def _check_text(value, label: str) -> str:
    text = str(value or "").strip()
    if len(text) > MAX_TEXT_CHARS:
        raise ValueError(f"「{label}」最多 {MAX_TEXT_CHARS} 字。")
    return text


def _check_tones(value) -> list:
    if not isinstance(value, list):
        raise ValueError("說話的口氣請挑 1～2 個。")
    tones = list(dict.fromkeys(str(t).strip() for t in value if str(t).strip()))
    if not TONE_MIN <= len(tones) <= TONE_MAX:
        raise ValueError("說話的口氣請挑 1～2 個。")
    for tone in tones:
        if len(tone) > MAX_TONE_CHARS:
            raise ValueError(f"口氣「{tone}」太長了，最多 {MAX_TONE_CHARS} 字。")
    return tones


def _replace_fact(conn: Conn, brand_id: str, fact_type: str, value: str, *, actor: str,
                  params: dict | None = None) -> None:
    """One confirmed row per type: update the latest confirmed row, create one, or (empty value)
    delete it. `params` = the row's `params_json` (the tone fact's `{"tones": [...]}`)."""
    current = _latest_fact(conn, brand_id, fact_type)
    if not value:
        if current is not None:
            bi_repo.delete_brand_fact(conn, brand_id, current["id"], actor=actor)
        return
    if current is None:
        bi_repo.create_brand_fact(conn, brand_id, actor=actor, fact_type=fact_type,
                                  label=vocab.brand_fact_type_label(fact_type), value=value,
                                  status="confirmed", confirmed_by=actor, params_json=params)
    elif (current["value"], current.get("params_json")) != (value, params):
        bi_repo.update_brand_fact(conn, brand_id, current["id"], actor=actor, fact_type=fact_type,
                                  label=current["label"], value=value, params_json=params,
                                  source_reference_id=current.get("source_reference_id"),
                                  confidence=current.get("confidence"))


def put_identity(conn: Conn, brand_id: str, body: dict, *, actor: str) -> dict:
    positioning = _check_text(body.get("positioning"), "一句話說你的品牌")
    visual = _check_text(body.get("visual"), "畫面風格")
    tones = _check_tones(body.get("tone"))
    _replace_fact(conn, brand_id, "positioning", positioning, actor=actor)
    _replace_fact(conn, brand_id, "tone", "、".join(tones), actor=actor, params={"tones": tones})
    _replace_fact(conn, brand_id, "visual_base", visual, actor=actor)
    advance(conn, brand_id, STEP_IDENTITY)
    return get_identity(conn, brand_id)


# ---------------------------------------------------------------------------
# Step 4 證據與政策
# ---------------------------------------------------------------------------

_PROOF_LABELS = dict(vocab.PROOF_KINDS)


def _policy_type_view(spec: dict) -> dict:
    return {**spec, "offer_label": vocab.offer_label(spec["offer_key"])}


def _policy_shape(key: str, params: dict, sentence: str, offer_key: str | None, *,
                  label: str, source: str, note: str = "") -> dict:
    spec = vocab.POLICY_TYPES_BY_KEY.get(key)
    return {
        "key": key, "label": label, "group": spec["group"] if spec else "自訂", "params": params,
        "offer_key": offer_key, "offer_label": vocab.offer_label(offer_key) if offer_key else "",
        "sentence": sentence, "source": source, "note": note,
    }


def _ai_policy(item: dict) -> dict | None:
    key = item.get("key")
    spec = vocab.POLICY_TYPES_BY_KEY.get(key) if isinstance(key, str) else None
    if spec is None:
        return None
    raw = item.get("params")
    params: dict = raw if isinstance(raw, dict) else {}
    try:
        params = vocab.normalize_policy_params(spec["key"], params)
        sentence = vocab.policy_sentence(spec["key"], params)
    except ValueError:
        sentence = ""  # a param the scan could not read: the user fills it in on the step
    return _policy_shape(spec["key"], params, sentence, spec["offer_key"], label=spec["label"],
                         source="ai", note=str(item.get("note") or ""))


def get_evidence(conn: Conn, brand_id: str) -> dict:
    prefill = _prefill(conn, brand_id, STEP_EVIDENCE)
    proof = [{"id": f["id"], "fact_key": f["fact_key"], "text": f["value"], "source": "saved",
              "note": ""} for f in _confirmed_facts(conn, brand_id, "proof")]
    seen_proof = {(p["fact_key"], p["text"]) for p in proof}
    for item in prefill.get("proof") or []:
        if not isinstance(item, dict) or item.get("fact_key") not in _PROOF_LABELS:
            continue
        text = str(item.get("text") or "").strip()
        if text and (item["fact_key"], text) not in seen_proof:
            seen_proof.add((item["fact_key"], text))
            proof.append({"id": None, "fact_key": item["fact_key"], "text": text, "source": "ai",
                          "note": str(item.get("note") or "")})

    saved = bi_repo.list_brand_policies(conn, brand_id)
    exempt = next((p for p in saved if p["key"] == vocab.COOLING_OFF_EXEMPT_KEY), None)
    policies = [_policy_shape(p["key"], p["params"], p["sentence"], p["offer_key"],
                              label=p["label"], source="saved")
                for p in saved if p["key"] != vocab.COOLING_OFF_EXEMPT_KEY]
    seen_keys = {p["key"] for p in policies}
    for item in prefill.get("policies") or []:
        shaped = _ai_policy(item) if isinstance(item, dict) else None
        if shaped is not None and shaped["key"] not in seen_keys:
            seen_keys.add(shaped["key"])
            policies.append(shaped)

    brand = bi_repo.get_brand(conn, brand_id) or {}
    return {
        "proof": proof,
        "proof_kinds": [{"key": k, "label": label} for k, label in vocab.PROOF_KINDS],
        "policies": policies,
        "policy_types": [_policy_type_view(p) for p in vocab.POLICY_TYPES],
        "cooling_off": {"applies": exempt is None,
                        "disclosure": (exempt["params"].get("disclosure") or "") if exempt else ""},
        "forbidden": [{"id": r["id"], "text": r["content"]}
                      for r in _forbidden_rules(conn, brand_id)],
        "regime_label": REGIME_LABELS.get(brand.get("regulatory_regime") or "", ""),
    }


def _forbidden_rules(conn: Conn, brand_id: str) -> list:
    return [r for r in bi_repo.list_rules_for_brand(conn, brand_id)
            if r["rule_type"] == "forbidden_word" and r.get("product_id") is None]


def _check_proof(value, existing_ids: set) -> list:
    if not isinstance(value, list):
        raise ValueError("證據清單格式不對。")
    out = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("證據清單格式不對。")
        fact_key = item.get("fact_key")
        if fact_key not in _PROOF_LABELS:
            raise ValueError("證據要選一種：" + "、".join(_PROOF_LABELS.values()) + "。")
        text = _check_text(item.get("text"), _PROOF_LABELS[fact_key])
        fact_id = item.get("id") or None
        if fact_id is not None and fact_id not in existing_ids:
            raise ValueError("找不到要修改的證據，請重新整理後再試。")
        if text:  # an empty row is a slot the user left blank (「沒有就留空」)
            out.append({"id": fact_id, "fact_key": fact_key, "text": text})
    return out


def _check_policies(value, cooling_off) -> list:
    if not isinstance(value, list):
        raise ValueError("全店政策清單格式不對。")
    items = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("全店政策清單格式不對。")
        if item.get("key") == vocab.COOLING_OFF_EXEMPT_KEY:
            raise ValueError("7 天猶豫期請在「7 天猶豫期」那一列設定。")
        items.append({"key": item.get("key"), "params": item.get("params") or {},
                      "sentence": item.get("sentence")})
    cooling_off = cooling_off if isinstance(cooling_off, dict) else {"applies": True}
    if cooling_off.get("applies") is False:
        disclosure = str(cooling_off.get("disclosure") or "").strip()
        vocab.policy_sentence(vocab.COOLING_OFF_EXEMPT_KEY, {"disclosure": disclosure})  # length
        items.append({"key": vocab.COOLING_OFF_EXEMPT_KEY, "params": {"disclosure": disclosure}})
    return items


def _check_forbidden(value) -> list:
    if not isinstance(value, list):
        raise ValueError("不能講的話清單格式不對。")
    out = []
    for item in value:
        text = str(item.get("text") if isinstance(item, dict) else item or "").strip()
        if len(text) > MAX_FORBIDDEN_CHARS:
            raise ValueError(f"「不能講的話」每一條最多 {MAX_FORBIDDEN_CHARS} 字。")
        if text and text not in out:
            out.append(text)
    return out


def put_evidence(conn: Conn, brand_id: str, body: dict, *, actor: str) -> dict:
    """Full-list semantics per list. Everything is validated before anything is written; the
    policies go first because `save_brand_policies` validates its whole list before writing."""
    existing_proof = {f["id"]: f for f in _confirmed_facts(conn, brand_id, "proof")}
    proof = _check_proof(body.get("proof", []), set(existing_proof))
    policies = _check_policies(body.get("policies", []), body.get("cooling_off"))
    forbidden = _check_forbidden(body.get("forbidden", []))

    bi_repo.save_brand_policies(conn, brand_id, policies, actor=actor)

    kept = {p["id"] for p in proof if p["id"]}
    for fact_id in set(existing_proof) - kept:
        bi_repo.delete_brand_fact(conn, brand_id, fact_id, actor=actor)
    for item in proof:
        label = _PROOF_LABELS[item["fact_key"]]
        before = existing_proof.get(item["id"]) if item["id"] else None
        if before is None:
            bi_repo.create_brand_fact(conn, brand_id, actor=actor, fact_type="proof", label=label,
                                      value=item["text"], status="confirmed", confirmed_by=actor,
                                      fact_key=item["fact_key"])
        elif (before["fact_key"], before["value"]) != (item["fact_key"], item["text"]):
            bi_repo.update_brand_fact(conn, brand_id, before["id"], actor=actor, fact_type="proof",
                                      label=label, value=item["text"], fact_key=item["fact_key"],
                                      source_reference_id=before.get("source_reference_id"),
                                      confidence=before.get("confidence"))

    rules = _forbidden_rules(conn, brand_id)
    for rule in rules:
        if rule["content"] not in forbidden:
            bi_repo.delete_rule(conn, brand_id, rule["id"], actor=actor)
    have = {r["content"] for r in rules}
    for text in forbidden:
        if text not in have:
            bi_repo.create_rule(conn, brand_id, actor=actor, rule_type="forbidden_word",
                                content=text, severity="hard")
    advance(conn, brand_id, STEP_EVIDENCE)
    return get_evidence(conn, brand_id)


# ---------------------------------------------------------------------------
# Step 5 素材
# ---------------------------------------------------------------------------

def get_media(conn: Conn, brand_id: str) -> dict:
    brand = bi_repo.get_brand(conn, brand_id) or {}
    return {"media": brand.get("media_capability")}


def put_media(conn: Conn, brand_id: str, body: dict, *, actor: str) -> dict:
    media = body.get("media")
    if media not in bi_repo.MEDIA_CAPABILITIES:
        raise ValueError("請選一個：只有照片，或照片和影片都能交。")
    brand = bi_repo.get_brand(conn, brand_id) or {}
    if brand.get("media_capability") != media:
        bi_repo.set_media_capability(conn, brand_id, media, actor=actor)
    advance(conn, brand_id, STEP_MEDIA)
    return get_media(conn, brand_id)


# ---------------------------------------------------------------------------
# Step 6 接工具
# ---------------------------------------------------------------------------

def connector_catalogue() -> list:
    return json.loads(_CATALOGUE_FILE.read_text(encoding="utf-8"))["connectors"]


def get_tools(conn: Conn, brand_id: str, *, bound_account_names: list) -> dict:
    """`bound_account_names` = names of the Meta ad accounts bound to this brand (the router
    reads them through `app.meta.repository`)."""
    connectors = []
    for row in connector_catalogue():
        state_ = "available" if row["live"] else "seat"
        note = "" if row["live"] else "即將開放"
        if row["key"] == "meta" and bound_account_names:
            state_, note = "connected", "已接上：" + "、".join(bound_account_names)
        link = row.get("link")
        connectors.append({
            "key": row["key"], "group": row["group"], "label": row["label"], "icon": row["icon"],
            "reads": row["reads"], "state": state_, "note": note,
            "link": link.replace("{brand_id}", brand_id) if link else None,
        })
    brand = bi_repo.get_brand(conn, brand_id) or {}
    return {
        "connectors": connectors,
        "conversion_goal": brand.get("conversion_goal"),
        "conversion_goal_options": [
            {"key": key, "label": vocab.CONVERSION_GOAL_LABELS.get(key, key)}
            for key in bi_repo.CONVERSION_GOALS
        ],
    }
