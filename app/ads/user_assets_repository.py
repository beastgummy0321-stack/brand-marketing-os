"""Brand-owned originals, durable upload attempts and immutable placement revisions.

One current placement per (campaign, asset, ad): the same original may back several planned
ads with their own copy (F40-I02); `ad_id` is NULL for library attaches.
"""

from datetime import date

from app.ads import repository as campaigns
from app.brand_intelligence import repository as brands
from app.core.db import jsonb, new_id

MAX_BYTES = 50 * 1024 * 1024


class PlacementConflict(ValueError):
    def __init__(self, current):
        super().__init__("同檔已有不同文案，請確認目前版本後明確更新。")
        self.current = dict(current)


def _brand(conn, org, brand):
    row = brands.get_brand(conn, brand)
    if row is None or row["org_id"] != org:
        raise ValueError("找不到品牌。")


def create_batch(conn, org, brand, files, actor):
    _brand(conn, org, brand)
    if not isinstance(files, list) or not 1 <= len(files) <= 10:
        raise ValueError("每批請選擇 1 至 10 個檔案。")
    batch = new_id("aub")
    conn.execute(
        "INSERT INTO ads_asset_upload_batch(id,org_id,brand_id,created_by) VALUES(%s,%s,%s,%s)",
        (batch, org, brand, actor),
    )
    for index, item in enumerate(files):
        if not isinstance(item, dict):
            raise ValueError("檔案描述必須是物件。")
        filename = item.get("filename")
        if not isinstance(filename, str) or not filename or len(filename) > 512:
            raise ValueError("檔名無效。")
        size = item.get("size")
        if isinstance(size, bool) or not isinstance(size, int) or not -(2**63) <= size < 2**63:
            raise ValueError("請提供檔案大小。")
        copy_fields = validate_copy(item.get("copy_fields") or {})
        valid = 0 < size <= MAX_BYTES
        conn.execute(
            "INSERT INTO ads_asset_upload(id,org_id,brand_id,batch_id,ordinal,filename,"
            "expected_size,"
            "supplied_mime,copy_fields,status,error) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                new_id("auu"),
                org,
                brand,
                batch,
                index,
                filename,
                size,
                item.get("content_type"),
                jsonb(copy_fields),
                "pending" if valid else "failed",
                None if valid else "單檔必須介於 1 byte 與 50 MiB。",
            ),
        )
    conn.commit()
    return batch_detail(conn, org, brand, batch)


def batch_detail(conn, org, brand, batch):
    row = conn.execute(
        "SELECT * FROM ads_asset_upload_batch WHERE org_id=%s AND brand_id=%s AND id=%s",
        (org, brand, batch),
    ).fetchone()
    if row is None:
        raise ValueError("找不到上傳批次。")
    uploads = conn.execute(
        "SELECT * FROM ads_asset_upload WHERE org_id=%s AND brand_id=%s AND batch_id=%s "
        "ORDER BY ordinal",
        (org, brand, batch),
    ).fetchall()
    return {**dict(row), "uploads": [dict(u) for u in uploads]}


def get_upload(conn, org, brand, upload_id):
    if not isinstance(upload_id, str) or not upload_id or len(upload_id) > 200:
        raise ValueError("上傳識別碼無效。")
    row = conn.execute(
        "SELECT * FROM ads_asset_upload WHERE org_id=%s AND brand_id=%s AND id=%s",
        (org, brand, upload_id),
    ).fetchone()
    if row is None:
        raise ValueError("找不到上傳紀錄。")
    return dict(row)


def get_asset(conn, org, brand, asset_id):
    if not isinstance(asset_id, str) or not asset_id or len(asset_id) > 200:
        raise ValueError("素材識別碼無效。")
    row = conn.execute(
        "SELECT * FROM ads_user_asset WHERE org_id=%s AND brand_id=%s AND id=%s",
        (org, brand, asset_id),
    ).fetchone()
    if row is None:
        raise ValueError("找不到品牌原檔。")
    return dict(row)


def list_assets(conn, org, brand, after=None, upload_after=None):
    rows = conn.execute(
        "SELECT * FROM ads_user_asset WHERE org_id=%s AND brand_id=%s "
        "AND (%s::text IS NULL OR id>%s) ORDER BY id LIMIT 101",
        (org, brand, after, after),
    ).fetchall()
    uploads = conn.execute(
        "SELECT * FROM ads_asset_upload WHERE org_id=%s AND brand_id=%s "
        "AND (%s::text IS NULL OR id>%s) ORDER BY id LIMIT 101",
        (org, brand, upload_after, upload_after),
    ).fetchall()
    return {
        "assets": [dict(r) for r in rows[:100]],
        "next_cursor": rows[99]["id"] if len(rows) > 100 else None,
        "uploads": [dict(r) for r in uploads[:100]],
        "next_upload_cursor": uploads[99]["id"] if len(uploads) > 100 else None,
    }


def set_upload(conn, org, brand, upload_id, **values):
    allowed = {
        "status",
        "error",
        "storage_key",
        "sha256",
        "mime_type",
        "byte_size",
        "asset_id",
        "orphan_keys",
    }
    if set(values) - allowed:
        raise ValueError("上傳欄位無效。")
    conn.execute(
        "UPDATE ads_asset_upload SET "
        + ",".join(k + "=%s" for k in values)
        + ",updated_at=now() WHERE org_id=%s AND brand_id=%s AND id=%s",
        (
            *(jsonb(v) if k == "orphan_keys" else v for k, v in values.items()),
            org,
            brand,
            upload_id,
        ),
    )
    conn.commit()


def finalize_original(conn, org, brand, upload_id):
    upload = get_upload(conn, org, brand, upload_id)
    row = conn.execute(
        "INSERT INTO ads_user_asset(id,org_id,brand_id,sha256,storage_key,filename,"
        "mime_type,byte_size) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(org_id,brand_id,sha256) DO NOTHING "
        "RETURNING *",
        (
            new_id("aua"),
            org,
            brand,
            upload["sha256"],
            upload["storage_key"],
            upload["filename"],
            upload["mime_type"],
            upload["byte_size"],
        ),
    ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT * FROM ads_user_asset WHERE org_id=%s AND brand_id=%s AND sha256=%s",
            (org, brand, upload["sha256"]),
        ).fetchone()
    assert row is not None
    orphans = list(upload["orphan_keys"])
    if row["storage_key"] != upload["storage_key"] and upload["storage_key"] not in orphans:
        orphans.append(upload["storage_key"])
    set_upload(
        conn,
        org,
        brand,
        upload_id,
        status="complete",
        asset_id=row["id"],
        error=None,
        orphan_keys=orphans,
    )
    return dict(row)


def validate_copy(value):
    if (
        not isinstance(value, dict)
        or len(value) > 20
        or any(
            not isinstance(k, str) or not isinstance(v, str) or len(k) > 80 or len(v) > 12000
            for k, v in value.items()
        )
    ):
        raise ValueError("文案必須是文字欄位。")
    return value


APPLY_COPY_EMPTY = "三欄都是空的，沒有可以套用的內容。"


def apply_copy(current, typed):
    """``current`` copy with every non-blank field of ``typed`` written over it; a blank field
    keeps the current text. Refused when every typed field is blank."""
    validate_copy(typed)
    filled = {key: value for key, value in typed.items() if value.strip()}
    if not filled:
        raise ValueError(APPLY_COPY_EMPTY)
    return {**(current or {}), **filled}


def placement(conn, org, brand, campaign_id, placement_id, revision=None):
    row = conn.execute(
        "SELECT * FROM ads_asset_placement WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND id=%s AND ((%s::integer IS NULL AND is_current) OR revision=%s)",
        (org, brand, campaign_id, placement_id, revision, revision),
    ).fetchone()
    if row is None:
        raise ValueError("找不到素材安排。")
    return dict(row)


def list_placements(conn, org, brand, campaign_id, history=False):
    if campaigns.get_campaign(conn, org, brand, campaign_id) is None:
        raise ValueError("找不到活動。")
    rows = conn.execute(
        "SELECT p.*,a.filename,a.mime_type,a.status AS asset_status,a.error AS asset_error "
        "FROM ads_asset_placement p JOIN ads_user_asset a ON a.id=p.asset_id "
        "WHERE p.org_id=%s AND p.brand_id=%s AND p.campaign_id=%s "
        "AND (%s OR p.is_current) ORDER BY p.created_at,p.revision",
        (org, brand, campaign_id, history),
    ).fetchall()
    return [dict(row) for row in rows]


def validate_purpose(value):
    """The same bound `revise` applies to `purpose`; None is "not set"."""
    if value is not None and (not isinstance(value, str) or len(value) > 4000):
        raise ValueError("安排文字欄位格式或長度無效。")
    return value


def attach(
    conn, org, brand, campaign_id, asset_id, copy_fields, actor, *, purpose=None, ad_id=None
):
    """`purpose` and `ad_id` are program-side keywords (the slot upload fills them with the ad's
    name and id); neither is a request-body field of `POST …/placements`, whose attaches keep
    `ad_id` NULL. The current row is keyed by (campaign, asset, ad): the same ad with different
    copy is a `PlacementConflict`; another ad with the same original is a second placement."""
    campaign = campaigns.get_campaign(conn, org, brand, campaign_id)
    if campaign is None:
        raise ValueError("找不到活動。")
    if campaign["status"] == "closed":
        raise ValueError("活動已結案，只能查看素材歷史。")
    get_asset(conn, org, brand, asset_id)
    validate_copy(copy_fields)
    validate_purpose(purpose)
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
        (f"asset-placement:{org}:{brand}:{campaign_id}:{asset_id}",),
    )
    existing = conn.execute(
        "SELECT * FROM ads_asset_placement WHERE org_id=%s AND brand_id=%s "
        "AND campaign_id=%s AND asset_id=%s AND ad_id IS NOT DISTINCT FROM %s AND is_current",
        (org, brand, campaign_id, asset_id, ad_id),
    ).fetchone()
    if existing:
        if existing["copy_fields"] != copy_fields:
            raise PlacementConflict(existing)
        return dict(existing)
    row = conn.execute(
        "INSERT INTO ads_asset_placement(id,revision,org_id,brand_id,campaign_id,asset_id,"
        "ad_id,copy_fields,purpose,created_by) "
        "VALUES(%s,1,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
        (
            new_id("aap"),
            org,
            brand,
            campaign_id,
            asset_id,
            ad_id,
            jsonb(copy_fields),
            purpose,
            actor,
        ),
    ).fetchone()
    return dict(row)


def attach_selected(
    conn, org, brand, campaign_id, body, actor, *, purpose=None, ad_id=None
):
    """Place a finished upload (`upload_id`, its own copy unless `copy_fields` is given) or a
    brand original (`asset_id`) in the campaign -- the placements route and the slot upload.
    `purpose` and `ad_id` are passed through to `attach` by the program only; the body keys are
    unchanged."""
    copy_fields = body.get("copy_fields")
    asset_id = body.get("asset_id")
    if body.get("upload_id"):
        item = get_upload(conn, org, brand, body["upload_id"])
        if item["status"] != "complete":
            raise ValueError(item["error"] or "此檔案仍未上傳完成。")
        asset_id = item["asset_id"]
        if copy_fields is None:
            copy_fields = item["copy_fields"]
    return attach(
        conn,
        org,
        brand,
        campaign_id,
        asset_id,
        {} if copy_fields is None else copy_fields,
        actor,
        purpose=purpose,
        ad_id=ad_id,
    )


def revise(conn, org, brand, campaign_id, placement_id, expected_revision, updates, actor):
    if (
        isinstance(expected_revision, bool)
        or not isinstance(expected_revision, int)
        or expected_revision < 1
    ):
        raise ValueError("請提供正整數版本。")
    for key, limit in (("purpose", 4000), ("destination_entity_id", 200)):
        value = updates.get(key)
        if value is not None and (not isinstance(value, str) or len(value) > limit):
            raise ValueError("安排文字欄位格式或長度無效。")
    for key in ("start_date", "end_date"):
        value = updates.get(key)
        if value is not None and not isinstance(value, (str, date)):
            raise ValueError("安排日期格式無效。")
    campaign = campaigns.get_campaign(conn, org, brand, campaign_id)
    if campaign is None or campaign["status"] == "closed":
        raise ValueError("活動已結案或不存在，只能查看素材歷史。")
    conn.execute(
        "SELECT id FROM ads_asset_placement WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND id=%s AND is_current FOR UPDATE",
        (org, brand, campaign_id, placement_id),
    )
    old = placement(conn, org, brand, campaign_id, placement_id)
    if old["revision"] != expected_revision:
        raise ValueError("素材安排已更新，請重新載入再修改。")
    if "apply_copy" in updates:
        # F47 Contract A (Q6): 「一份文案套到全部待處理」 -- an empty field keeps this placement's
        # current text; a field with text replaces it; all empty is refused (never a wipe).
        updates = {**updates}
        updates["copy_fields"] = apply_copy(old["copy_fields"], updates.pop("apply_copy"))
    allowed = {
        "copy_fields",
        "required",
        "purpose",
        "destination_entity_id",
        "start_date",
        "end_date",
    }
    if set(updates) - allowed:
        raise ValueError("不能直接修改安排確認或建議狀態。")
    if "copy_fields" in updates:
        validate_copy(updates["copy_fields"])
    if "required" in updates and not isinstance(updates["required"], bool):
        raise ValueError("必用旗標無效。")
    if not updates or all(old.get(k) == v for k, v in updates.items()):
        return old
    new = {**old, **updates}
    for key in ("start_date", "end_date"):
        if isinstance(new[key], str):
            try:
                new[key] = date.fromisoformat(new[key])
            except ValueError:
                raise ValueError("安排日期格式無效。") from None
    if new["start_date"] and new["end_date"] and new["end_date"] < new["start_date"]:
        raise ValueError("安排結束日期不能早於開始日期。")
    if (
        new["destination_entity_id"]
        and not conn.execute(
            "SELECT 1 FROM ads_external_entity WHERE org_id=%s AND brand_id=%s AND "
            "campaign_id=%s AND id=%s",
            (org, brand, campaign_id, new["destination_entity_id"]),
        ).fetchone()
    ):
        raise ValueError("目的節點不屬於此活動。")
    conn.execute(
        "UPDATE ads_asset_placement SET is_current=false WHERE id=%s AND revision=%s",
        (placement_id, old["revision"]),
    )
    row = conn.execute(
        "INSERT INTO ads_asset_placement(id,revision,org_id,brand_id,campaign_id,asset_id,ad_id,"
        "required,copy_fields,suggested_copy,destination_entity_id,purpose,start_date,end_date,"
        "unknowns,created_by) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
        (
            placement_id,
            old["revision"] + 1,
            org,
            brand,
            campaign_id,
            old["asset_id"],
            old["ad_id"],
            new["required"],
            jsonb(new["copy_fields"]),
            jsonb({}),
            new["destination_entity_id"],
            new["purpose"],
            new["start_date"],
            new["end_date"],
            jsonb(old["unknowns"]),
            actor,
        ),
    ).fetchone()
    return dict(row)
