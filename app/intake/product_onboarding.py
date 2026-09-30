"""app/intake/product_onboarding.py — product onboarding (F43-I05): what the products page, the
five product steps and the bundle page read and write (`#/plist`, `#/p1`–`#/p5`, `#/bundle` and the
`#/home` product block of `.harness/scratch/prototype/f41-onboarding/index.html`).

Every confirmed value lives in the store the F43 Decisions name and is written through the
`app.brand_intelligence.repository` facade (no SQL here). Every number and label the screens show
is computed here, never on the page: break-even (`app.ads.breakeven_cpa`, the one formula),
derived list price / cost (the facade's effective `get_product_economics`), offer labels (the
facade's `offer_sources`, the same rule as `available_offer_keys`) and 食安法 flags
(`app.workbench.validate_claims`, the public entry; the brand's regime). No model call.

A product being built has `product.onboarding_step` 1–5 (5 = the sell-ways are saved, 完成 not
pressed yet); each step's PUT moves it to at least step+1 (never back); 完成 sets it NULL. The
product-page read (`intake_product_prefill`, written by F43-I06) is shown on a step
(`source="ai"` + `note`) only while that step is not saved yet; a finished product only shows saved
values and every PUT edits in place.

Validation failures raise `ValueError` (router: 400 + the message); an unknown product / bundle
raises `NotFound` (router: 404). Entry points: the functions below, called only by
`app/intake/routes_product_api.py`.
"""

from pathlib import Path

from app import ads, workbench
from app.brand_intelligence import benchmarks as bi_benchmarks
from app.brand_intelligence import repository as bi_repo
from app.core import vocab
from app.core.db import Conn
from app.intake import repository as ir
from app.intake import state

STEP_WHAT, STEP_WHO, STEP_EVIDENCE, STEP_SELL_WAYS, STEP_DONE = range(1, 6)
STEP_LABELS = {
    STEP_WHAT: "商品是什麼",
    STEP_WHO: "誰會買",
    STEP_EVIDENCE: "證據與說法",
    STEP_SELL_WAYS: "賣法與價格",
    STEP_DONE: "完成",
}
# 「建到一半：還沒確認〈…〉」 on the products page, by the step the product stopped at.
_DRAFT_MISSING = {
    STEP_WHAT: "商品資料",
    STEP_WHO: "顧客",
    STEP_EVIDENCE: "證據與說法",
    STEP_SELL_WAYS: "賣法與價格",
    STEP_DONE: "完成",
}

PHOTO_KIND = "product_photo"
MAX_NAME_CHARS = 60
MAX_GROUPS = 3
MAX_PAINS = 2
MAX_CLAIM_CHARS = 100
LEAD_GOALS = ("lead", "booking")  # F05 rule 2: these brands see 成交率
_WHAT_FIELDS = (  # (body key, product_fact type, label, max chars)
    ("intro", "core_info", "一句話介紹", 200),
    ("mechanism", "mechanism", "裡面有什麼、怎麼作用", 500),
    ("difference", "differentiation", "跟別人不一樣的地方", 200),
)
_PROOF_LABELS = dict(vocab.PROOF_KINDS)
_PREFILL_STATUSES = ("running", "done", "failed")
_PREFILL_FAILED = "AI 讀商品頁失敗，可以重試，或直接自己填。"
_BENCHMARK_KEYS = ("gross_margin", "shipping_cost", "close_rate")
_ASSUMPTION_FIELDS = ("cost", "shipping", "close_rate")


class NotFound(Exception):
    """The product / bundle is not this brand's (router: 404)."""


# ---------------------------------------------------------------------------
# Shared reads
# ---------------------------------------------------------------------------


def _num(value) -> float | None:
    return None if value is None else float(value)


def _money_text(value) -> str:
    number = float(value)
    return f"{int(number):,}" if number == int(number) else f"{number:,.2f}"


def _is_knowledge(conn: Conn, brand_id: str, product: dict) -> bool:
    return product["parent_id"] is None and bi_repo.knowledge_product_ids(
        conn, brand_id, product["id"]
    ) == [product["id"]]


def _knowledge_product(conn: Conn, brand_id: str, product_id: str) -> dict:
    product = bi_repo.get_product(conn, brand_id, product_id)
    if product is None or not _is_knowledge(conn, brand_id, product):
        raise NotFound("找不到這個商品。")
    return product


def _brand(conn: Conn, brand_id: str) -> dict:
    return bi_repo.get_brand(conn, brand_id) or {}


def _show_close_rate(brand: dict) -> bool:
    return brand.get("conversion_goal") in LEAD_GOALS


def _prefill(conn: Conn, brand_id: str, product: dict, step: int) -> dict:
    """The product-page read's proposal for `step`: only while the product is being built and the
    step is not saved yet."""
    current = product.get("onboarding_step")
    if current is None or current > step:
        return {}
    value = (ir.get_product_prefill(conn, brand_id, product["id"]) or {}).get("prefill_json")
    return value if isinstance(value, dict) else {}


def _advance(conn: Conn, brand_id: str, product: dict, step: int, *, actor: str) -> None:
    current = product.get("onboarding_step")
    if current is not None and current < step + 1:
        bi_repo.set_product_onboarding_step(
            conn, brand_id, product["id"], min(step + 1, STEP_DONE), actor=actor
        )


def _photo_url(brand_id: str, asset: dict) -> str:
    # Served by the existing asset-file route (app/brand_web/routes.py `asset_file`).
    return f"/brands/{brand_id}/assets/file/{asset['id']}/{Path(asset['storage_key']).name}"


def _photo_assets(conn: Conn, brand_id: str) -> list:
    """Active product photos (the 商品照 path: `official_asset` with `product_id`), oldest first."""
    assets = [
        a
        for a in bi_repo.list_official_assets(conn, brand_id)
        if a.get("product_id") and a.get("status") == "active" and a.get("asset_kind") == PHOTO_KIND
    ]
    return sorted(assets, key=lambda a: (a["created_at"], a["id"]))


def _thumbnails(conn: Conn, brand_id: str) -> dict:
    """knowledge product id -> its newest photo URL."""
    return {a["product_id"]: _photo_url(brand_id, a) for a in _photo_assets(conn, brand_id)}


def _confirmed_facts(conn: Conn, brand_id: str, product_id: str, fact_type: str) -> list:
    return [
        f
        for f in bi_repo.list_product_facts(conn, brand_id, product_id, status="confirmed")
        if f["fact_type"] == fact_type
    ]


def _product_claims(conn: Conn, brand_id: str, product_id: str) -> list:
    return [
        c
        for c in bi_repo.list_claims_for_product(conn, brand_id, product_id)
        if c["product_id"] == product_id
    ]


def _text(value, label: str, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        raise ValueError(f"「{label}」最多 {limit} 字。")
    return text


def _check_name(value, label: str = "商品名稱") -> str:
    name = _text(value, label, MAX_NAME_CHARS)
    if not name:
        raise ValueError(f"請填寫{label}。")
    return name


def _check_url(value, label: str) -> str | None:
    url = str(value or "").strip()
    if url and state.invalid_url([url]):
        raise ValueError(f"{label}「{url}」不是有效的網址，請以 https:// 或 http:// 開頭。")
    return url or None


def _ai(block) -> dict:
    return block if isinstance(block, dict) else {}


def _ai_list(prefill: dict, key: str) -> list:
    return [i for i in prefill.get(key) or [] if isinstance(i, dict)]


# ---------------------------------------------------------------------------
# Money: one view for a sell-way row, a bundle and the products page
# ---------------------------------------------------------------------------


def _break_even(economics: dict | None) -> float | None:
    value = ads.breakeven_cpa(economics)
    return None if value is None else round(value, 2)


def _offers(conn: Conn, brand_id: str, sell_way: dict) -> tuple[list, list]:
    """(offer_labels, offer_notes) of one sell-way. Labels = `offer_sources` for it: its own price
    offer first (「組合價 省 198」 for more than one unit, 「優惠價 省 N」 for one), then each brand
    policy sentence that applies (a threshold policy only at or above its threshold). Notes = the
    threshold policies this price does not reach (「售價未滿 NT$999，不適用滿額免運」)."""
    policies = [
        p for p in bi_repo.list_brand_policies(conn, brand_id) if p["status"] == "confirmed"
    ]
    policy_sentences = {p["sentence"] for p in policies}
    econ = sell_way.get("economics") or {}
    own, brand_wide, applied = [], [], set()
    for row in bi_repo.offer_sources(conn, brand_id, sell_way["id"]):
        applied.add(row["sentence"])
        if row["sentence"] in policy_sentences:
            brand_wide.append(row["sentence"])
        else:  # the sell-way's own offer (list price above price)
            saved = float(econ["list_price"]) - float(econ["selling_price"])
            word = "組合價" if row["offer_key"] == "bundle" else "優惠價"
            own.append(f"{word} 省 {_money_text(saved)}")
    notes = []
    for policy in policies:
        spec = vocab.POLICY_TYPES_BY_KEY.get(policy["key"])
        threshold = policy["params"].get(spec["threshold"]) if spec and spec["threshold"] else None
        if (
            threshold
            and policy["offer_key"] not in (None, "none")
            and policy["sentence"] not in applied
        ):
            notes.append(f"售價未滿 NT${_money_text(threshold)}，不適用{policy['label']}")
    return own + list(dict.fromkeys(brand_wide)), notes


def _money(conn: Conn, brand_id: str, sell_way: dict, show_close_rate: bool) -> dict:
    econ = sell_way.get("economics") or {}
    derived = econ.get("derived_fields") or []
    units = sum(c["qty"] for c in sell_way["components"]) or 1
    break_even = _break_even(econ or None)
    cap = econ.get("cap_per_sale")
    labels, notes = _offers(conn, brand_id, sell_way)
    list_derived, cost_derived = "list_price" in derived, "unit_variable_cost" in derived
    out = {
        "price": _num(econ.get("selling_price")),
        "list_price": _num(econ.get("list_price")),
        "list_price_derived": list_derived,
        "list_price_note": ("同售價" if units == 1 else f"{units} 件單價相加")
        if list_derived
        else "",
        "cost": _num(econ.get("unit_variable_cost")),
        "cost_derived": cost_derived,
        "cost_note": f"{units} 件成本相加" if cost_derived else "",
        "shipping": _num(econ.get("shipping_cost")),
        "break_even": break_even,
        "cap_per_sale": _num(cap) if cap is not None else break_even,
        "cap_is_default": cap is None,
        "landing_url": sell_way.get("effective_landing_url") or "",
        "landing_is_default": sell_way.get("landing_url") is None,
        "offer_labels": labels,
        "offer_notes": notes,
        "assumptions": list(econ.get("assumptions_json") or []),
    }
    if show_close_rate:
        out["close_rate"] = _num(econ.get("close_rate"))
    return out


def _benchmarks(show_close_rate: bool) -> dict:
    """F05 「不知道 → 參考值」: the values the 進階 fold fills (and flags in `assumptions`)."""
    return {
        key: {
            "value": bi_benchmarks.get(key)["value"],
            "source_text": bi_benchmarks.source_text(key),
        }
        for key in _BENCHMARK_KEYS
        if key != "close_rate" or show_close_rate
    }


def _number(item: dict, key: str, label: str, owner: str) -> float | None:
    value = item.get(key)
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"「{owner}」的{label}請填數字。")
    if value < 0:
        raise ValueError(f"「{owner}」的{label}不能是負數。")
    return value


def _check_money(item: dict, owner: str, show_close_rate: bool) -> dict:
    """The raw money inputs of one sell-way / bundle -> `save_sell_way`'s `economics`. Empty list
    price / cost / cap = derived / break-even."""
    price = _number(item, "price", "售價", owner)
    if not price:
        raise ValueError(f"「{owner}」的售價要大於 0。")
    close_rate = _number(item, "close_rate", "成交率", owner) if show_close_rate else None
    if close_rate is not None and not 0 < close_rate <= 1:
        raise ValueError(f"「{owner}」的成交率要在 0 到 1 之間（例如 0.2＝20%）。")
    assumptions = item.get("assumptions") or []
    if not isinstance(assumptions, list) or not set(assumptions) <= set(_ASSUMPTION_FIELDS):
        raise ValueError("「參考值」只能標在成本、運費或成交率。")
    return {
        "selling_price": price,
        "list_price": _number(item, "list_price", "原價", owner),
        "unit_variable_cost": _number(item, "cost", "成本", owner),
        "shipping_cost": _number(item, "shipping", "運費成本", owner),
        "cap_per_sale": _number(item, "cap_per_sale", "每筆上限", owner),
        "close_rate": close_rate,
        "assumptions": [a for a in _ASSUMPTION_FIELDS if a in assumptions] or None,
    }


# ---------------------------------------------------------------------------
# Products page (`GET|POST …/products`)
# ---------------------------------------------------------------------------


def _summary(conn: Conn, brand_id: str, product: dict) -> str:
    step = product.get("onboarding_step")
    if step is not None:
        return f"建到一半：還沒確認{_DRAFT_MISSING[step]}"
    groups = len(bi_repo.list_customer_groups(conn, brand_id, product["id"]))
    proof = len(_confirmed_facts(conn, brand_id, product["id"], "proof"))
    claims = sum(
        1 for c in _product_claims(conn, brand_id, product["id"]) if c["claim_type"] == "approved"
    )
    return f"{groups} 群顧客・證據 {proof}・說法 {claims}"


def _sell_way_brief(conn: Conn, brand_id: str, sell_way: dict) -> dict:
    money = _money(conn, brand_id, sell_way, False)
    return {
        "id": sell_way["id"],
        "name": sell_way["display_name"],
        "price": money["price"],
        "break_even": money["break_even"],
        "offer_labels": money["offer_labels"],
    }


def list_page(conn: Conn, brand_id: str) -> dict:
    """`GET …/products`: knowledge products (creation order) with their sell-ways, bundles, and the
    brand scan's products not created yet (F42 prefill, 「AI 讀到了，還沒確認」)."""
    products = sorted(
        bi_repo.list_products(conn, brand_id), key=lambda p: (p["created_at"], p["id"])
    )
    sell_ways = bi_repo.list_sell_ways(conn, brand_id)
    sell_way_ids = {s["id"] for s in sell_ways}
    active_ways = [s for s in sell_ways if s["status"] == "active"]
    by_id = {p["id"]: p for p in products}
    thumbs = _thumbnails(conn, brand_id)
    items = []
    for product in products:
        if (
            product["status"] != "active"
            or product["parent_id"] is not None
            or product["id"] in sell_way_ids
        ):
            continue
        step = product.get("onboarding_step")
        items.append(
            {
                "id": product["id"],
                "name": product["name"],
                "thumbnail_url": thumbs.get(product["id"]),
                "state": "ready" if step is None else "draft",
                "step": step,
                "summary": _summary(conn, brand_id, product),
                "sell_ways": [
                    _sell_way_brief(conn, brand_id, s)
                    for s in active_ways
                    if s["kind"] == "single" and s["parent_id"] == product["id"]
                ],
            }
        )
    bundles = []
    for bundle in (s for s in active_ways if s["kind"] == "bundle"):
        ids = [c["product_id"] for c in bundle["components"]]
        brief = _sell_way_brief(conn, brand_id, bundle)
        ready = all(by_id.get(i, {}).get("onboarding_step") is None for i in ids)
        bundles.append(
            {
                **brief,
                "thumbnails": [thumbs[i] for i in ids if i in thumbs],
                "state": "ready" if ready else "draft",
                "components": [
                    {k: c[k] for k in ("product_id", "name", "qty")} for c in bundle["components"]
                ],
            }
        )
    taken = {p["name"].strip().casefold() for p in products if p["parent_id"] is None}
    return {
        "products": items,
        "bundles": bundles,
        "suggestions": _suggestions(conn, brand_id, taken),
    }


def _suggestions(conn: Conn, brand_id: str, taken: set) -> list:
    row = ir.get_active_draft(conn, brand_id) or ir.get_latest_completed_draft(conn, brand_id)
    prefill = _ai((row or {}).get("prefill_json"))
    out = []
    for item in _ai_list(prefill, "products"):
        name = str(item.get("name") or "").strip()
        if name and name.casefold() not in taken:
            taken.add(name.casefold())
            out.append({"name": name, "url": str(item.get("url") or "").strip() or None})
    return out


def create(conn: Conn, brand_id: str, body: dict, *, actor: str) -> dict:
    """`POST …/products` `{name, page_url?}`: a new knowledge product at step 1. A product of the
    same name is that product (Contract W, as `create_product`): its id is returned unchanged."""
    name = _check_name(body.get("name"))
    page_url = _check_url(body.get("page_url"), "商品頁網址")
    same = next(
        (
            p
            for p in bi_repo.list_products(conn, brand_id)
            if p["status"] == "active"
            and p["parent_id"] is None
            and p["name"].strip().casefold() == name.casefold()
        ),
        None,
    )
    if same is not None:
        if not _is_knowledge(conn, brand_id, same):
            raise ValueError(f"已經有叫「{name}」的組合了，商品換個名字。")
        return {"product_id": same["id"], "created": False}
    product = bi_repo.create_product(conn, brand_id, name=name, actor=actor)
    bi_repo.set_product_onboarding_step(conn, brand_id, product["id"], STEP_WHAT, actor=actor)
    if page_url:
        bi_repo.set_product_page_url(conn, brand_id, product["id"], page_url, actor=actor)
    return {"product_id": product["id"], "created": True}


# ---------------------------------------------------------------------------
# Status / 完成
# ---------------------------------------------------------------------------


def _prefill_status(conn: Conn, brand_id: str, product_id: str) -> tuple[str, str | None]:
    row = ir.get_product_prefill(conn, brand_id, product_id)
    if row is None:
        return "none", None
    status_ = row.get("status")
    if status_ not in _PREFILL_STATUSES:
        status_ = "done" if row.get("prefill_json") is not None else "none"
    if status_ != "failed":
        return status_, None
    error = _ai(row.get("prefill_json")).get("error")
    return "failed", str(error) if error else _PREFILL_FAILED


def status(conn: Conn, brand_id: str, product_id: str) -> dict:
    """`GET …/products/{p}/onboarding`: 1–5 while being built (5 = 賣法 saved, 完成 not pressed);
    a finished product reads step 5, completed."""
    product = _knowledge_product(conn, brand_id, product_id)
    step = product.get("onboarding_step")
    prefill_status, prefill_error = _prefill_status(conn, brand_id, product_id)
    return {
        "step": step or STEP_DONE,
        "completed": step is None,
        "prefill_status": prefill_status,
        "prefill_error": prefill_error,
    }


def _active_singles(conn: Conn, brand_id: str, product_id: str) -> list:
    return [
        s
        for s in bi_repo.list_sell_ways(conn, brand_id, product_id)
        if s["kind"] == "single" and s["parent_id"] == product_id and s["status"] == "active"
    ]


def complete(conn: Conn, brand_id: str, product_id: str, *, actor: str) -> dict:
    """`POST …/onboarding/complete`: idempotent on a finished product; refused while a step is not
    saved yet (the step stopped before 賣法 was saved) or the product has no sell-way."""
    product = _knowledge_product(conn, brand_id, product_id)
    step = product.get("onboarding_step")
    if step is not None:
        if step < STEP_DONE:
            raise ValueError(f"「{STEP_LABELS[step]}」還沒存，先存好這一步再完成。")
        if not _active_singles(conn, brand_id, product_id):
            raise ValueError("至少要有一種賣法才能完成商品建檔。")
        bi_repo.set_product_onboarding_step(conn, brand_id, product_id, None, actor=actor)
    return status(conn, brand_id, product_id)


# ---------------------------------------------------------------------------
# Step 1 商品是什麼
# ---------------------------------------------------------------------------


def _text_field(saved: dict | None, ai: dict) -> dict:
    if saved is not None:
        return {"value": saved["value"], "source": "saved", "note": ""}
    value = str(ai.get("value") or "").strip()
    if value:
        return {"value": value, "source": "ai", "note": str(ai.get("note") or "")}
    return {"value": "", "source": "none", "note": ""}


def _photos(conn: Conn, brand_id: str, product_id: str) -> list:
    return [
        {"id": a["id"], "url": _photo_url(brand_id, a)}
        for a in _photo_assets(conn, brand_id)
        if a["product_id"] == product_id
    ]


def get_what(conn: Conn, brand_id: str, product_id: str) -> dict:
    product = _knowledge_product(conn, brand_id, product_id)
    prefill = _prefill(conn, brand_id, product, STEP_WHAT)
    out = {
        "name": product["name"],
        "page_url": product.get("page_url") or "",
        "photos": _photos(conn, brand_id, product_id),
    }
    for key, fact_type, _label, _limit in _WHAT_FIELDS:
        facts = _confirmed_facts(conn, brand_id, product_id, fact_type)
        out[key] = _text_field(facts[-1] if facts else None, _ai(prefill.get(key)))
    return out


def _replace_fact(
    conn: Conn, brand_id: str, product_id: str, fact_type: str, value: str, *, actor: str
) -> None:
    """One confirmed row per type: update the latest, create one, or (empty) delete it."""
    facts = _confirmed_facts(conn, brand_id, product_id, fact_type)
    current = facts[-1] if facts else None
    if not value:
        if current is not None:
            bi_repo.delete_product_fact(conn, brand_id, current["id"], actor=actor)
    elif current is None:
        bi_repo.create_product_fact(
            conn,
            brand_id,
            product_id,
            actor=actor,
            fact_type=fact_type,
            label=vocab.product_fact_type_label(fact_type),
            value=value,
            status="confirmed",
            confirmed_by=actor,
        )
    elif current["value"] != value:
        bi_repo.update_product_fact(
            conn,
            brand_id,
            product_id,
            current["id"],
            actor=actor,
            fact_type=fact_type,
            label=current["label"],
            value=value,
            source_reference_id=current.get("source_reference_id"),
            confidence=current.get("confidence"),
        )


def _rename(conn: Conn, brand_id: str, product: dict, name: str, *, actor: str) -> None:
    """Rename the product and keep its single sell-ways' 「〈商品〉 · 〈賣法〉」 names (F05)."""
    old_prefix = f"{product['name']} · "
    bi_repo.update_product(
        conn, brand_id, product["id"], name=name, status=product["status"], actor=actor
    )
    for way in bi_repo.list_sell_ways(conn, brand_id, product["id"]):
        if way["parent_id"] == product["id"] and way["name"].startswith(old_prefix):
            bi_repo.update_product(
                conn,
                brand_id,
                way["id"],
                status=way["status"],
                actor=actor,
                name=f"{name} · {way['name'][len(old_prefix) :]}",
            )


def put_what(conn: Conn, brand_id: str, product_id: str, body: dict, *, actor: str) -> dict:
    """`{name, page_url, intro, mechanism, difference, photo_ids?}`. New photos come from the
    existing official-asset upload (`asset_kind=product_photo`, `product_id`); `photo_ids`
    (optional) = the product photos to keep (absent = keep all)."""
    product = _knowledge_product(conn, brand_id, product_id)
    name = _check_name(body.get("name"))
    page_url = _check_url(body.get("page_url"), "商品頁網址")
    texts = {
        fact_type: _text(body.get(key), label, limit)
        for key, fact_type, label, limit in _WHAT_FIELDS
    }
    current = _photos(conn, brand_id, product_id)
    keep = body.get("photo_ids")
    if keep is not None:
        keep = {str(i) for i in (keep if isinstance(keep, list) else [keep])}
        if keep - {p["id"] for p in current}:
            raise ValueError("找不到要保留的商品照。")

    if name != product["name"]:
        _rename(conn, brand_id, product, name, actor=actor)
    if (product.get("page_url") or None) != page_url:
        bi_repo.set_product_page_url(conn, brand_id, product_id, page_url, actor=actor)
    for fact_type, value in texts.items():
        _replace_fact(conn, brand_id, product_id, fact_type, value, actor=actor)
    for photo in current:
        if keep is not None and photo["id"] not in keep:
            bi_repo.delete_official_asset(conn, brand_id, photo["id"], actor=actor)
    _advance(conn, brand_id, product, STEP_WHAT, actor=actor)
    return get_what(conn, brand_id, product_id)


# ---------------------------------------------------------------------------
# Step 2 誰會買
# ---------------------------------------------------------------------------


def _ai_group(item: dict) -> dict | None:
    who = str(item.get("who") or "").strip()
    pains = [k for k in dict.fromkeys(item.get("pain_keys") or []) if k in vocab.PAIN_KEYS]
    if not who or not pains:
        return None
    return {
        "id": None,
        "who": who,
        "pain_keys": pains[:MAX_PAINS],
        "quote": str(item.get("quote") or "").strip(),
        "when_used": str(item.get("when_used") or "").strip(),
        "source": "ai",
        "note": str(item.get("note") or ""),
    }


def get_who(conn: Conn, brand_id: str, product_id: str) -> dict:
    product = _knowledge_product(conn, brand_id, product_id)
    groups = [
        {
            "id": g["id"],
            "who": g["who"],
            "pain_keys": list(g["pain_keys"]),
            "quote": g["quote"] or "",
            "when_used": g["when_used"] or "",
            "source": "saved",
            "note": "",
        }
        for g in bi_repo.list_customer_groups(conn, brand_id, product_id)
    ]
    if not groups:
        shaped = (
            _ai_group(i) for i in _ai_list(_prefill(conn, brand_id, product, STEP_WHO), "groups")
        )
        groups = [g for g in shaped if g is not None][:MAX_GROUPS]
    return {
        "groups": groups,
        "pain_options": [{"key": key, "label": label} for key, label in vocab.PAIN_KINDS],
    }


def _check_group(item, n: int, existing: dict) -> dict:
    if not isinstance(item, dict):
        raise ValueError("顧客群格式不對。")
    who = _text(item.get("who"), f"第 {n} 群：是誰", 100)
    if not who:
        raise ValueError(f"第 {n} 群還沒寫是誰。")
    pains = item.get("pain_keys")
    if not isinstance(pains, list) or not pains:
        raise ValueError(f"第 {n} 群要挑 1～2 個買之前最煩的事。")
    pains = list(dict.fromkeys(str(k) for k in pains))
    unknown = [k for k in pains if k not in vocab.PAIN_KEYS]
    if unknown:
        raise ValueError(f"第 {n} 群的煩惱「{unknown[0]}」不在六種煩惱裡。")
    if len(pains) > MAX_PAINS:
        raise ValueError(f"第 {n} 群最多挑 {MAX_PAINS} 個煩惱。")
    before = existing.get(item.get("id"))
    source = item.get("source")
    if source not in ("ai", "custom", "user"):
        source = before["source"] if before is not None and source == "saved" else "user"
    return {
        "who": who,
        "pain_keys": pains,
        "source": source,
        "quote": _text(item.get("quote"), f"第 {n} 群：顧客會怎麼說", 200),
        "when_used": _text(item.get("when_used"), f"第 {n} 群：什麼時候用", 100),
    }


def put_who(conn: Conn, brand_id: str, product_id: str, body: dict, *, actor: str) -> dict:
    """`{groups: [{id?, who, pain_keys (1–2 of the six), quote, when_used, source?}]}` (≤3, full
    list). `source`: ai (an accepted proposal) / custom (from 自訂) / user; `saved` keeps the
    row's."""
    product = _knowledge_product(conn, brand_id, product_id)
    groups = body.get("groups")
    if not isinstance(groups, list):
        raise ValueError("顧客群格式不對。")
    if len(groups) > MAX_GROUPS:
        raise ValueError(f"顧客最多 {MAX_GROUPS} 群。")
    existing = {g["id"]: g for g in bi_repo.list_customer_groups(conn, brand_id, product_id)}
    checked = [_check_group(item, n, existing) for n, item in enumerate(groups, start=1)]
    bi_repo.save_customer_groups(conn, brand_id, product_id, checked, actor=actor)
    _advance(conn, brand_id, product, STEP_WHO, actor=actor)
    return get_who(conn, brand_id, product_id)


# ---------------------------------------------------------------------------
# Step 3 證據與說法
# ---------------------------------------------------------------------------


def _statutory(conn: Conn, brand: dict, text: str) -> dict | None:
    """The 食安法 flag of one claim sentence (`workbench.validate_claims`, brand regime): the first
    hit's term and 「〈term〉屬〈tier〉（〈basis〉）」; None without a hit (or without a regime)."""
    result = workbench.validate_claims(conn, brand["org_id"], brand["id"], None, text)
    hits = result["statutory_hits"]
    if not hits:
        return None
    tiers = {
        t["term"]: t["tier_label"] for t in (result["statutory_warning"] or {}).get("terms", [])
    }
    hit = hits[0]
    return {
        "term": hit["term"],
        "sentence": f"「{hit['term']}」屬{tiers.get(hit['term'], '')}（{hit['basis']}）",
    }


_VERDICTS = {"approved": "ok", "forbidden": "no"}


def get_evidence(conn: Conn, brand_id: str, product_id: str) -> dict:
    product = _knowledge_product(conn, brand_id, product_id)
    brand = _brand(conn, brand_id)
    prefill = _prefill(conn, brand_id, product, STEP_EVIDENCE)
    proof = [
        {
            "id": f["id"],
            "fact_key": f["fact_key"],
            "text": f["value"],
            "source": "saved",
            "note": "",
        }
        for f in _confirmed_facts(conn, brand_id, product_id, "proof")
    ]
    seen = {(p["fact_key"], p["text"]) for p in proof}
    for item in _ai_list(prefill, "proof"):
        text = str(item.get("text") or "").strip()
        if item.get("fact_key") in _PROOF_LABELS and text and (item["fact_key"], text) not in seen:
            seen.add((item["fact_key"], text))
            proof.append(
                {
                    "id": None,
                    "fact_key": item["fact_key"],
                    "text": text,
                    "source": "ai",
                    "note": str(item.get("note") or ""),
                }
            )
    claims = [
        {
            "id": c["id"],
            "text": c["claim_text"],
            "from_note": "",
            "source": "saved",
            "verdict": _VERDICTS.get(c["claim_type"]),
        }
        for c in _product_claims(conn, brand_id, product_id)
    ]
    seen_text = {c["text"] for c in claims}
    for item in _ai_list(prefill, "claims"):
        text = str(item.get("text") or "").strip()
        if text and text not in seen_text:
            seen_text.add(text)
            claims.append(
                {
                    "id": None,
                    "text": text,
                    "from_note": str(item.get("note") or ""),
                    "source": "ai",
                    "verdict": None,
                }
            )
    for claim in claims:
        claim["statutory"] = _statutory(conn, brand, claim["text"])
        if claim["statutory"] is not None:
            claim["verdict"] = "no"
    return {
        "proof": proof,
        "proof_kinds": [{"key": k, "label": label} for k, label in vocab.PROOF_KINDS],
        "claims": claims,
    }


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
        text = _text(item.get("text"), _PROOF_LABELS[fact_key], 200)
        fact_id = item.get("id") or None
        if fact_id is not None and fact_id not in existing_ids:
            raise ValueError("找不到要修改的證據，請重新整理後再試。")
        if text:  # an empty row is a slot left blank (「沒有就留空」)
            out.append({"id": fact_id, "fact_key": fact_key, "text": text})
    return out


def _check_claims(conn: Conn, brand: dict, value, existing_ids: set) -> list:
    """Each claim needs 可以講／不能講; a 食安法 hit is 不能講 whatever was sent."""
    if not isinstance(value, list):
        raise ValueError("說法清單格式不對。")
    out, seen, unset = [], set(), 0
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("說法清單格式不對。")
        text = _text(item.get("text"), "說法", MAX_CLAIM_CHARS)
        claim_id = item.get("id") or None
        if claim_id is not None and claim_id not in existing_ids:
            raise ValueError("找不到要修改的說法，請重新整理後再試。")
        if not text or text in seen:
            continue
        seen.add(text)
        verdict = item.get("verdict")
        if verdict not in ("ok", "no", None):
            raise ValueError("每一句說法請選「可以講」或「不能講」。")
        if _statutory(conn, brand, text) is not None:
            verdict = "no"
        elif verdict is None:
            unset += 1
        out.append({"id": claim_id, "text": text, "verdict": verdict})
    if unset:
        raise ValueError(f"還有 {unset} 句沒選「可以講」或「不能講」。")
    return out


def put_evidence(conn: Conn, brand_id: str, product_id: str, body: dict, *, actor: str) -> dict:
    """`{proof: [{id?, fact_key, text}], claims: [{id?, text, verdict: ok|no}]}` — full lists.
    Everything is validated before anything is written."""
    product = _knowledge_product(conn, brand_id, product_id)
    brand = _brand(conn, brand_id)
    existing_proof = {f["id"]: f for f in _confirmed_facts(conn, brand_id, product_id, "proof")}
    existing_claims = {c["id"]: c for c in _product_claims(conn, brand_id, product_id)}
    proof = _check_proof(body.get("proof", []), set(existing_proof))
    claims = _check_claims(conn, brand, body.get("claims", []), set(existing_claims))

    for fact_id in set(existing_proof) - {p["id"] for p in proof if p["id"]}:
        bi_repo.delete_product_fact(conn, brand_id, fact_id, actor=actor)
    for item in proof:
        label, before = _PROOF_LABELS[item["fact_key"]], existing_proof.get(item["id"] or "")
        if before is None:
            bi_repo.create_product_fact(
                conn,
                brand_id,
                product_id,
                actor=actor,
                fact_type="proof",
                label=label,
                value=item["text"],
                status="confirmed",
                confirmed_by=actor,
                fact_key=item["fact_key"],
            )
        elif (before["fact_key"], before["value"]) != (item["fact_key"], item["text"]):
            bi_repo.update_product_fact(
                conn,
                brand_id,
                product_id,
                before["id"],
                actor=actor,
                fact_type="proof",
                label=label,
                value=item["text"],
                fact_key=item["fact_key"],
                source_reference_id=before.get("source_reference_id"),
                confidence=before.get("confidence"),
            )

    for claim_id in set(existing_claims) - {c["id"] for c in claims if c["id"]}:
        bi_repo.delete_claim(conn, brand_id, claim_id, actor=actor)
    for item in claims:
        claim_type = "approved" if item["verdict"] == "ok" else "forbidden"
        before = existing_claims.get(item["id"] or "")
        if before is None:
            bi_repo.create_claim(
                conn,
                brand_id,
                actor=actor,
                claim_text=item["text"],
                claim_type=claim_type,
                product_id=product_id,
            )
        elif (before["claim_text"], before["claim_type"]) != (item["text"], claim_type):
            bi_repo.update_claim(
                conn,
                brand_id,
                before["id"],
                actor=actor,
                claim_text=item["text"],
                claim_type=claim_type,
                product_id=product_id,
                evidence_source_reference_id=before.get("evidence_source_reference_id"),
            )
    _advance(conn, brand_id, product, STEP_EVIDENCE, actor=actor)
    return get_evidence(conn, brand_id, product_id)


# ---------------------------------------------------------------------------
# Step 4 賣法與價格
# ---------------------------------------------------------------------------


def _sell_way_row(
    conn: Conn, brand_id: str, product: dict, way: dict, show_close_rate: bool
) -> dict:
    components = [{k: c[k] for k in ("product_id", "name", "qty")} for c in way["components"]]
    if not components:  # an F05 sell-way written before F43 (no component rows): one unit
        components = [{"product_id": product["id"], "name": product["name"], "qty": 1}]
    return {
        "id": way["id"],
        "name": way["display_name"],
        "components": components,
        "qty": components[0]["qty"],
        **_money(conn, brand_id, way, show_close_rate),
        "source": "saved",
        "note": "",
    }


def _ai_sell_way(product: dict, item: dict, show_close_rate: bool) -> dict | None:
    name, qty, price = str(item.get("name") or "").strip(), item.get("qty"), item.get("price")
    list_price = item.get("list_price")
    if (
        not name
        or isinstance(qty, bool)
        or not isinstance(qty, int)
        or qty <= 0
        or isinstance(price, bool)
        or not isinstance(price, (int, float))
        or price <= 0
    ):
        return None
    if isinstance(list_price, bool) or not isinstance(list_price, (int, float)) or list_price < 0:
        list_price = None
    row = {
        "id": None,
        "name": name,
        "components": [{"product_id": product["id"], "name": product["name"], "qty": qty}],
        "qty": qty,
        "price": float(price),
        "list_price": _num(list_price),
        "list_price_derived": False,
        "list_price_note": "",
        "cost": None,
        "cost_derived": False,
        "cost_note": "",
        "shipping": None,
        "break_even": None,
        "cap_per_sale": None,
        "cap_is_default": True,
        "landing_url": product.get("page_url") or "",
        "landing_is_default": True,
        "offer_labels": [],
        "offer_notes": [],
        "assumptions": [],
        "source": "ai",
        "note": str(item.get("note") or ""),
    }
    if show_close_rate:
        row["close_rate"] = None
    return row


def get_sell_ways(conn: Conn, brand_id: str, product_id: str) -> dict:
    """The product's active single sell-ways (creation order); none saved yet -> the page read's
    proposals (unsaved, no numbers derived)."""
    product = _knowledge_product(conn, brand_id, product_id)
    show = _show_close_rate(_brand(conn, brand_id))
    rows = [
        _sell_way_row(conn, brand_id, product, w, show)
        for w in _active_singles(conn, brand_id, product_id)
    ]
    if not rows:
        shaped = (
            _ai_sell_way(product, i, show)
            for i in _ai_list(_prefill(conn, brand_id, product, STEP_SELL_WAYS), "sell_ways")
        )
        rows = [r for r in shaped if r is not None]
    return {"sell_ways": rows, "show_close_rate": show, "assumptions": _benchmarks(show)}


def _check_sell_ways(value, existing: dict, show_close_rate: bool) -> list:
    if not isinstance(value, list) or not value:
        raise ValueError("至少要有一種賣法。")
    by_name = {w["display_name"].casefold(): w["id"] for w in existing.values()}
    out, names = [], set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("賣法清單格式不對。")
        name = _check_name(item.get("name"), "賣法名稱")
        if name.casefold() in names:
            raise ValueError(f"賣法「{name}」重複了。")
        names.add(name.casefold())
        qty = item.get("qty", 1)
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise ValueError(f"「{name}」的數量要是正整數。")
        way_id = item.get("id") or None
        if way_id is not None and way_id not in existing:
            raise ValueError("找不到要修改的賣法，請重新整理後再試。")
        out.append(
            {
                "id": way_id,
                "name": name,
                "qty": qty,
                "economics": _check_money(item, name, show_close_rate),
                "landing_url": _check_url(item.get("landing_url"), f"「{name}」的落地頁"),
            }
        )
    sent = {c["id"] for c in out if c["id"]}
    for row in out:  # a new row named like an existing sell-way not sent is that sell-way
        match = by_name.get(row["name"].casefold())
        if row["id"] is None and match is not None and match not in sent:
            row["id"] = match
            sent.add(match)
    return out


def put_sell_ways(conn: Conn, brand_id: str, product_id: str, body: dict, *, actor: str) -> dict:
    """`{sell_ways: [{id?, name, qty, price, list_price?, cost?, shipping?, close_rate?,
    cap_per_sale?, landing_url?, assumptions?}]}` — the full list of this product's single
    sell-ways, raw inputs only (empty list price / cost / cap = derived / break-even; empty landing
    = the product page). A sell-way left out is archived (campaigns may still point at it)."""
    product = _knowledge_product(conn, brand_id, product_id)
    show = _show_close_rate(_brand(conn, brand_id))
    existing = {w["id"]: w for w in _active_singles(conn, brand_id, product_id)}
    rows = _check_sell_ways(body.get("sell_ways"), existing, show)
    kept = {r["id"] for r in rows if r["id"]}
    for way_id, way in existing.items():
        if way_id not in kept:
            bi_repo.update_product(
                conn, brand_id, way_id, name=way["name"], status="archived", actor=actor
            )
    for row in rows:
        bi_repo.save_sell_way(
            conn,
            brand_id,
            sell_way_id=row["id"],
            name=row["name"],
            components=[{"product_id": product_id, "qty": row["qty"]}],
            economics=row["economics"],
            landing_url=row["landing_url"],
            actor=actor,
        )
    _advance(conn, brand_id, product, STEP_SELL_WAYS, actor=actor)
    return get_sell_ways(conn, brand_id, product_id)


# ---------------------------------------------------------------------------
# Bundles (`#/bundle`): a sell-way of several finished products
# ---------------------------------------------------------------------------


def _require_bundle(conn: Conn, brand_id: str, bundle_id: str) -> dict:
    way = next(
        (
            w
            for w in bi_repo.list_sell_ways(conn, brand_id)
            if w["id"] == bundle_id and w["kind"] == "bundle"
        ),
        None,
    )
    if way is None:
        raise NotFound("找不到這個組合。")
    return way


def _unit_numbers(conn: Conn, brand_id: str, product_id: str) -> tuple:
    """(price, cost) of the product's one-unit sell-way with confirmed numbers (earliest)."""
    for way in _active_singles(conn, brand_id, product_id):
        econ = way.get("economics")
        if (
            [(c["product_id"], c["qty"]) for c in way["components"]] == [(product_id, 1)]
            and econ
            and econ["status"] == "confirmed"
        ):
            return _num(econ["selling_price"]), _num(econ["unit_variable_cost"])
    return None, None


def _reused(conn: Conn, brand_id: str, components: list) -> dict:
    """「廣告會用到的」: the components' customer groups and proof (reused, not copied)."""
    groups, proof = [], []
    for comp in components:
        for g in bi_repo.list_customer_groups(conn, brand_id, comp["product_id"]):
            groups.append(
                {
                    "product_id": comp["product_id"],
                    "product_name": comp["name"],
                    "who": g["who"],
                    "pain_labels": [vocab.pain_label(k) for k in g["pain_keys"]],
                }
            )
        for f in _confirmed_facts(conn, brand_id, comp["product_id"], "proof"):
            proof.append(
                {
                    "product_id": comp["product_id"],
                    "product_name": comp["name"],
                    "fact_key": f["fact_key"],
                    "label": _PROOF_LABELS.get(f["fact_key"], ""),
                    "text": f["value"],
                }
            )
    return {"groups": groups, "proof": proof}


def get_bundle(conn: Conn, brand_id: str, bundle_id: str) -> dict:
    way = _require_bundle(conn, brand_id, bundle_id)
    show = _show_close_rate(_brand(conn, brand_id))
    thumbs = _thumbnails(conn, brand_id)
    components = []
    for comp in way["components"]:
        price, cost = _unit_numbers(conn, brand_id, comp["product_id"])
        components.append(
            {
                "product_id": comp["product_id"],
                "name": comp["name"],
                "qty": comp["qty"],
                "thumbnail_url": thumbs.get(comp["product_id"]),
                "unit_price": price,
                "unit_cost": cost,
            }
        )
    return {
        "id": way["id"],
        "name": way["name"],
        "status": way["status"],
        "components": components,
        **_money(conn, brand_id, way, show),
        "show_close_rate": show,
        "benchmarks": _benchmarks(show),
        "reused": _reused(conn, brand_id, components),
    }


def _check_components(conn: Conn, brand_id: str, value) -> list:
    if not isinstance(value, list):
        raise ValueError("組合裡的商品格式不對。")
    out, seen = [], set()
    for item in value:
        product_id = item.get("product_id") if isinstance(item, dict) else None
        product = (
            bi_repo.get_product(conn, brand_id, product_id) if isinstance(product_id, str) else None
        )
        if product is None or not _is_knowledge(conn, brand_id, product):
            raise ValueError("組合裡有找不到的商品，請重新整理後再試。")
        if product.get("onboarding_step") is not None:
            raise ValueError(f"「{product['name']}」還沒建完，建完才能放進組合。")
        qty = item.get("qty", 1)
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise ValueError(f"「{product['name']}」的數量要是正整數。")
        if product_id in seen:
            raise ValueError(f"「{product['name']}」在組合裡重複了，改數量就好。")
        seen.add(product_id)
        out.append({"product_id": product_id, "qty": qty})
    if len(out) < 2:
        raise ValueError("組合至少要放兩個不同的商品；同一個商品多件，請到那個商品的賣法新增。")
    return out


def save_bundle(
    conn: Conn, brand_id: str, bundle_id: str | None, body: dict, *, actor: str
) -> dict:
    """`POST …/bundles` (bundle_id None) / `PUT …/bundles/{id}`: `{name, components: [{product_id,
    qty}], price, list_price?, cost?, shipping?, close_rate?, cap_per_sale?, landing_url?,
    assumptions?}` — raw inputs; empty list price / cost = the components' sums."""
    if bundle_id is not None:
        _require_bundle(conn, brand_id, bundle_id)
    name = _check_name(body.get("name"), "組合名稱")
    components = _check_components(conn, brand_id, body.get("components"))
    economics = _check_money(body, name, _show_close_rate(_brand(conn, brand_id)))
    landing_url = _check_url(body.get("landing_url"), "落地頁")
    if bundle_id is None and any(
        p["status"] == "active"
        and p["parent_id"] is None
        and p["name"].strip().casefold() == name.casefold()
        for p in bi_repo.list_products(conn, brand_id)
    ):
        raise ValueError(f"已經有叫「{name}」的商品或組合了，換個名字。")
    saved = bi_repo.save_sell_way(
        conn,
        brand_id,
        sell_way_id=bundle_id,
        name=name,
        components=components,
        economics=economics,
        landing_url=landing_url,
        actor=actor,
    )
    return get_bundle(conn, brand_id, saved["id"])
