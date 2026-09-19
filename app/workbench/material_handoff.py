"""Scoped upstream seams for saved sources and explicit generation.

Opaque source references are stored, not interpreted. Prepared packs do not enqueue
models. The upstream owns durable approval and whether an uncertain request may retry.
"""

import json
from contextlib import contextmanager

from app.brand_intelligence import repository as brands
from app.workbench import image_cards, repository


@contextmanager
def _lock(conn, org, brand, source):
    key = "workbench-handoff:" + json.dumps([org, brand, source], sort_keys=True)
    conn.execute("SELECT pg_advisory_lock(hashtextextended(%s,0))", (key,))
    try:
        yield
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (key,))


def _brand(conn, org, brand):
    row = brands.get_brand(conn, brand)
    if not row or row["org_id"] != org:
        raise ValueError("找不到品牌。")


def prepare(conn, org, brand, pack):
    """Idempotently prepare exactly one upstream set, without a model call."""
    _brand(conn, org, brand)
    sets = pack.get("sets")
    if not isinstance(sets, list) or len(sets) != 1:
        raise ValueError("每次交棒需有一個獨立素材任務。")
    item = sets[0]
    required = item.get("required_outputs")
    if required not in ({"copy": 1}, {"image_prompt": 1}):
        raise ValueError("任務只接受獨立文案或圖片提示詞。")
    source = pack.get("source_ref")
    if not isinstance(source, dict) or not source:
        raise ValueError("交棒需有可追溯來源。")
    with _lock(conn, org, brand, source):
        existing = repository.pack_for_source(conn, org, brand, "schedule_node", source)
        pack_id = (
            existing["id"]
            if existing
            else repository.create_pack(
                conn,
                org,
                brand,
                {**pack, "source_kind": "schedule_node"},
            )
        )
        found = conn.execute(
            "SELECT id FROM workbench_brief WHERE org_id=%s AND brand_id=%s AND pack_id=%s",
            (org, brand, pack_id),
        ).fetchone()
        if not found:
            repository.submit_brief(
                conn,
                org,
                brand,
                {
                    "source_kind": "schedule_node",
                    "source_ref": source,
                    "request": {**item.get("request", {}), "parts": list(required)},
                    "product_id": item.get("product_id"),
                    "coordinates": item.get("coordinates", {}),
                },
                pack_id=pack_id,
                name=item.get("name"),
                required_outputs=required,
                enqueue_generation=False,
            )
        return pack_id


def start(conn, org, brand, pack_id):
    """One explicit enqueue only; queued/running/finished sets are never restarted here."""
    _brand(conn, org, brand)
    with _lock(conn, org, brand, {"pack": pack_id}):
        row = conn.execute(
            "SELECT id,status,required_outputs_json FROM workbench_brief"
            " WHERE org_id=%s AND brand_id=%s AND pack_id=%s",
            (org, brand, pack_id),
        ).fetchone()
        if not row:
            raise ValueError("找不到這個品牌的素材任務包。")
        if row["status"] != "idle":
            return
        repository.run_product(
            conn, org, brand, row["id"], next(iter(row["required_outputs_json"]))
        )


def options(conn, org, brand, *, part=None):
    _brand(conn, org, brand)
    rows = conn.execute(
        "SELECT o.id,o.brief_id,o.part,o.body_json,o.version_index,b.name,b.request_json"
        " FROM workbench_output o JOIN workbench_brief b"
        " ON b.org_id=o.org_id AND b.brand_id=o.brand_id AND b.id=o.brief_id"
        " WHERE o.org_id=%s AND o.brand_id=%s AND o.part IN ('copy','image_prompt')"
        " AND (%s::text IS NULL OR o.part=%s) ORDER BY o.created_at DESC,o.id LIMIT 100",
        (org, brand, part, part),
    ).fetchall()
    result = []
    for row in rows:
        body = repository._slice_body(row["part"], row["body_json"], row["version_index"])
        if not isinstance(body, dict):
            continue
        base = {"set_id": row["brief_id"], "version_id": row["id"], "part": row["part"]}
        if row["part"] == "copy":
            fields = {
                k: body[k]
                for k in ("body", "headline", "description")
                if isinstance(body.get(k), str)
            }
            result.append(
                {
                    **base,
                    "card_index": None,
                    "label": f"{row['name'] or '文案'} · 版本 {row['version_index']}",
                    "text": "\n".join(fields.values()),
                    "copy_fields": fields,
                }
            )
        else:
            cards = image_cards.prompt_cards(
                body, version_index=row["version_index"], selected=False, variant_count=0
            )
            for index, card in enumerate(cards):
                result.append(
                    {
                        **base,
                        "card_index": index,
                        "label": f"{row['name'] or '圖片提示詞'} · {card['label']}",
                        "text": card["text"],
                    }
                )
    return result


def source(conn, org, brand, set_id, version_id, card_index=None):
    # Exact source lookup must still work after the recent-options page rolls over.
    _brand(conn, org, brand)
    row = conn.execute(
        "SELECT o.part,o.body_json,o.version_index,b.pack_id FROM workbench_output o"
        " JOIN workbench_brief b ON b.id=o.brief_id AND b.org_id=o.org_id"
        " AND b.brand_id=o.brand_id"
        " WHERE o.org_id=%s AND o.brand_id=%s AND o.brief_id=%s AND o.id=%s",
        (org, brand, set_id, version_id),
    ).fetchone()
    if not row or row["part"] not in ("copy", "image_prompt"):
        raise ValueError("找不到此品牌的提示詞或文案版本。")
    body = repository._slice_body(row["part"], row["body_json"], row["version_index"])
    if not isinstance(body, dict):
        raise ValueError("這個版本沒有可用文字。")
    fields = {
        k: body[k] for k in ("body", "headline", "description") if isinstance(body.get(k), str)
    }
    if row["part"] == "copy":
        return {
            "source": "workbench",
            "set_id": set_id,
            "version_id": version_id,
            "card_index": None,
            "part": "copy",
            "pack_id": row["pack_id"],
            "text": "\n".join(fields.values()),
            "copy_fields": fields,
        }
    cards = image_cards.prompt_cards(
        body, version_index=row["version_index"], selected=False, variant_count=0
    )
    index = 0 if card_index is None else card_index
    if type(index) is not int or not 0 <= index < len(cards):
        raise ValueError("找不到這張提示詞卡。")
    return {
        "source": "workbench",
        "set_id": set_id,
        "version_id": version_id,
        "card_index": index,
        "part": "image_prompt",
        "pack_id": row["pack_id"],
        "text": cards[index]["text"],
    }
