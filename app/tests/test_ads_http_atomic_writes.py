"""R1: rejected business edits leave committed PostgreSQL rows unchanged."""

from datetime import date
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from app import main
from app.ads import brief, manual_settings, material_tasks, repository
from app.brand_intelligence import repository as brands
from app.core import db

from .identity_test_helpers import mint_hs256


@pytest.fixture
def campaign():
    conn = db.current()
    brand = brands.create_brand(conn, org_id=db.DEV_ORG_ID, name="Atomic audit",
                                client_name=None, actor="test")
    products = [brands.create_product(conn, brand["id"], name=name, actor="test")
                for name in ("Original", "Replacement")]
    groups = [brands.save_customer_groups(conn, brand["id"], product["id"],
              [{"who": "Test audience", "pain_keys": ["cost"]}], actor="test")
              for product in products]
    row = repository.create_campaign(conn, db.DEV_ORG_ID, brand["id"], {
        "name": "Original campaign", "goal_text": "Purchase", "objective": "購買",
        "start_date": date(2026, 10, 1), "end_date": date(2026, 10, 31),
        "context_json": {"product_ids": [products[0]["id"]],
                         "customer_group_ids": [groups[0][0]["id"]],
                         "landing_url": "https://example.com/original"},
    })
    conn.commit()
    return brand["id"], row["id"], products[1]["id"], groups[1][0]["id"]


def snapshot(campaign):
    brand, campaign_id, _, _ = campaign
    # This is a different physical connection from both the fixture and HTTP request.
    with db.connection() as observer:
        row = repository.get_campaign(observer, db.DEV_ORG_ID, brand, campaign_id)
        return {key: row[key] for key in ("name", "context_json", "budget_basis_json")}


def patch(client, campaign, **payload):
    brand, campaign_id, _, _ = campaign
    return client.patch(f"/api/ads/brands/{brand}/campaigns/{campaign_id}", json=payload)


@pytest.mark.parametrize("invalid,code", [
    ({"landing_url": "javascript:alert(1)"}, "landing_url_invalid"),
    ({"customer_group_ids": ["missing-group"]}, "customer_group_unknown"),
])
def test_rejected_patch_restores_name_product_and_dependent_fields(campaign, invalid, code):
    before = snapshot(campaign)
    response = patch(TestClient(main.app), campaign, name="Changed", product_ids=[campaign[2]],
                     **invalid)
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == code
    assert snapshot(campaign) == before


@pytest.mark.parametrize("owner,name", [
    (repository, "update_campaign"), (brief, "set_landing_url"),
    (brief, "set_customer_groups"),
])
def test_failure_after_each_write_cannot_escape_through_helper_commit(campaign, monkeypatch,
                                                                    owner, name):
    before = snapshot(campaign)
    original = getattr(owner, name)

    def fail_after_write(conn, *args, **kwargs):
        original(conn, *args, **kwargs)
        conn.commit()
        raise ValueError("injected_failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(owner, name, fail_after_write)
        response = patch(TestClient(main.app), campaign, name="Changed", product_ids=[campaign[2]],
                         landing_url="https://example.com/new", customer_group_ids=[campaign[3]])
    assert response.status_code == 400, response.text
    assert snapshot(campaign) == before
    retry = patch(TestClient(main.app), campaign, name="Changed", product_ids=[campaign[2]],
                  landing_url="https://example.com/new", customer_group_ids=[campaign[3]])
    assert retry.status_code == 200, retry.text
    after = snapshot(campaign)
    assert after["name"] == "Changed"
    assert after["context_json"]["product_ids"] == [campaign[2]]
    assert after["context_json"]["customer_group_ids"] == [campaign[3]]
    assert after["context_json"]["landing_url"] == "https://example.com/new"


def test_nested_helper_failure_rolls_back_whole_patch(campaign, monkeypatch):
    before = snapshot(campaign)
    original = brief.set_landing_url

    def nested(conn, *args, **kwargs):
        with conn.atomic():
            original(conn, *args, **kwargs)
            conn.commit()
            raise ValueError("nested_failure")

    monkeypatch.setattr(brief, "set_landing_url", nested)
    response = patch(TestClient(main.app), campaign, name="Changed",
                     landing_url="https://example.com/new")
    assert response.status_code == 400, response.text
    assert snapshot(campaign) == before


def test_other_brand_cannot_patch_campaign(campaign):
    before = snapshot(campaign)
    brand = brands.create_brand(db.current(), org_id=db.DEV_ORG_ID,
                               name="Other brand", client_name=None, actor="test")
    db.current().commit()
    response = TestClient(main.app).patch(
        f"/api/ads/brands/{brand['id']}/campaigns/{campaign[1]}", json={"name": "Changed"})
    assert response.status_code == 404, response.text
    assert snapshot(campaign) == before


def test_manual_settings_late_validation_failure_is_atomic(campaign, monkeypatch):
    brand, campaign_id, _, _ = campaign
    group = repository.create_group(db.current(), db.DEV_ORG_ID, brand, campaign_id,
                                    channel_key="meta", name="Group", role="new", daily_budget=100)
    db.current().commit()
    before = snapshot(campaign)
    original = manual_settings.save

    def late_failure(conn, *args, **kwargs):
        original(conn, *args, **kwargs)
        raise ValueError("manual_settings_invalid")

    monkeypatch.setattr(manual_settings, "save", late_failure)
    response = TestClient(main.app).put(
        f"/api/ads/brands/{brand}/campaigns/{campaign_id}/groups/{group['id']}/manual-settings",
        json={"values": {"landing_url": "https://example.com/new"}})
    assert response.status_code == 400, response.text
    assert snapshot(campaign) == before


def test_other_org_cannot_patch_campaign(campaign):
    before = snapshot(campaign)
    user = uuid4()
    token = mint_hs256(sub=str(user), email=f"atomic-{user.hex[:8]}@example.com")
    # TestClient's project default token is applied after constructor headers.
    client = TestClient(main.app)
    client.headers["Authorization"] = f"Bearer {token}"
    response = patch(client, campaign, name="Foreign change")
    assert response.status_code == 404, response.text
    assert snapshot(campaign) == before


@pytest.mark.parametrize("write_step", ["_write", "_remember"])
def test_material_failure_restores_task_revision_and_operation_identity(campaign, monkeypatch,
                                                                      write_step):
    brand, campaign_id, _, _ = campaign
    original = getattr(material_tasks, write_step)

    def late_failure(conn, *args, **kwargs):
        original(conn, *args, **kwargs)
        conn.commit()
        raise ValueError("injected material failure")

    path = f"/api/ads/brands/{brand}/campaigns/{campaign_id}/material-tasks"
    body = {"operation_id": "atomic-create", "title": "Material", "mode": "copy"}
    with monkeypatch.context() as scoped:
        scoped.setattr(material_tasks, write_step, late_failure)
        response = TestClient(main.app).post(path, json=body)
    assert response.status_code == 409, response.text
    with db.connection() as observer:
        for table in ("ads_material_task", "ads_material_revision", "ads_material_operation"):
            assert observer.execute(
                f"SELECT count(*) AS n FROM {table} WHERE campaign_id=%s", (campaign_id,)
            ).fetchone()["n"] == 0
    retry = TestClient(main.app).post(path, json=body)
    assert retry.status_code == 200, retry.text
    repeated = TestClient(main.app).post(path, json=body)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["task"]["id"] == retry.json()["task"]["id"]


def test_material_update_late_failure_preserves_revision_and_retry(campaign, monkeypatch):
    brand, campaign_id, _, _ = campaign
    client = TestClient(main.app)
    path = f"/api/ads/brands/{brand}/campaigns/{campaign_id}/material-tasks"
    task = client.post(path, json={"operation_id": "create", "title": "Original",
                                  "mode": "copy"}).json()["task"]
    original = material_tasks._remember

    def late_failure(conn, *args, **kwargs):
        original(conn, *args, **kwargs)
        conn.commit()
        raise ValueError("injected update failure")

    body = {"operation_id": "update", "expected_revision": 1, "title": "Updated"}
    with monkeypatch.context() as scoped:
        scoped.setattr(material_tasks, "_remember", late_failure)
        response = client.patch(f"{path}/{task['id']}", json=body)
    assert response.status_code == 409, response.text
    with db.connection() as observer:
        observed = material_tasks.get(observer, db.DEV_ORG_ID, brand, campaign_id, task["id"])
        assert observed["revision"] == 1
        assert observed["title"] == "Original"
        assert observer.execute("SELECT count(*) AS n FROM ads_material_revision WHERE task_id=%s",
                                (task["id"],)).fetchone()["n"] == 1
    retry = client.patch(f"{path}/{task['id']}", json=body)
    assert retry.status_code == 200, retry.text
    assert retry.json()["task"]["revision"] == 2


def test_material_cancel_response_failure_does_not_leave_cancelled_row(campaign, monkeypatch):
    brand, campaign_id, _, _ = campaign
    client = TestClient(main.app)
    path = f"/api/ads/brands/{brand}/campaigns/{campaign_id}/material-tasks"
    task = client.post(path, json={"operation_id": "create", "title": "Original",
                                  "mode": "copy"}).json()["task"]
    def fail_response(*args, **kwargs):
        raise ValueError("injected response failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(material_tasks, "get", fail_response)
        response = client.post(f"{path}/{task['id']}/cancel")
    assert response.status_code == 409, response.text
    with db.connection() as observer:
        observed = material_tasks.get(observer, db.DEV_ORG_ID, brand, campaign_id, task["id"])
        assert observed["cancelled_at"] is None
    retry = client.post(f"{path}/{task['id']}/cancel")
    assert retry.status_code == 200, retry.text
    assert retry.json()["task"]["cancelled_at"] is not None


def try_material_lock(brand):
    # Never borrow a pooled connection: a leaked session lock is reentrant on its
    # owning backend, which would conceal the failure this probe must detect.
    key = f"ads-material:{db.DEV_ORG_ID}:{brand}"
    with psycopg.connect(db.dsn(), autocommit=True) as observer:
        acquired = observer.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s,0))", (key,)
        ).fetchone()[0]
        if acquired:
            observer.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (key,))
        return acquired


def test_material_http_commit_holds_lock_until_business_rows_are_visible(campaign, monkeypatch):
    brand, campaign_id, _, _ = campaign
    original = material_tasks.create
    observed = []

    def before_owner_finishes(conn, *args, **kwargs):
        result = original(conn, *args, **kwargs)
        # The service lock context has exited, but the HTTP operation has not.
        observed.append(try_material_lock(brand))
        with db.connection() as observer:
            assert observer.execute(
                "SELECT count(*) AS n FROM ads_material_task WHERE campaign_id=%s", (campaign_id,)
            ).fetchone()["n"] == 0
        return result

    monkeypatch.setattr(material_tasks, "create", before_owner_finishes)
    response = TestClient(main.app).post(
        f"/api/ads/brands/{brand}/campaigns/{campaign_id}/material-tasks",
        json={"operation_id": "locked-create", "title": "Material", "mode": "copy"})
    assert response.status_code == 200, response.text
    assert observed == [False]
    assert try_material_lock(brand) is True
    with db.connection() as observer:
        assert observer.execute(
            "SELECT count(*) AS n FROM ads_material_task WHERE campaign_id=%s", (campaign_id,)
        ).fetchone()["n"] == 1


def test_material_sql_failure_releases_lock_without_masking_the_original_error(campaign,
                                                                              monkeypatch):
    brand, campaign_id, _, _ = campaign
    original = material_tasks._write
    path = f"/api/ads/brands/{brand}/campaigns/{campaign_id}/material-tasks"
    body = {"operation_id": "sql-failure", "title": "Material", "mode": "copy"}

    def sql_failure(conn, *args, **kwargs):
        original(conn, *args, **kwargs)
        conn.execute("SELECT 1 / 0")

    with monkeypatch.context() as scoped:
        scoped.setattr(material_tasks, "_write", sql_failure)
        with pytest.raises(psycopg.errors.DivisionByZero):
            TestClient(main.app).post(path, json=body)
    assert try_material_lock(brand) is True
    with db.connection() as observer:
        assert observer.execute(
            "SELECT count(*) AS n FROM ads_material_task WHERE campaign_id=%s", (campaign_id,)
        ).fetchone()["n"] == 0
    retry = TestClient(main.app).post(path, json=body)
    assert retry.status_code == 200, retry.text
    assert try_material_lock(brand) is True


def test_material_nested_success_keeps_lock_through_outer_operation(campaign):
    brand, campaign_id, _, _ = campaign
    conn = db.current()
    conn.execute("SELECT 1")
    with conn.atomic():
        with conn.atomic():
            task = material_tasks.create(conn, db.DEV_ORG_ID, brand, campaign_id, {
                "operation_id": "nested-create", "title": "Material", "mode": "copy"}, "test")
        # RELEASE SAVEPOINT must not release a successful business lock.
        assert try_material_lock(brand) is False
        conn.commit()
        assert try_material_lock(brand) is False
    assert try_material_lock(brand) is False
    conn.commit()
    assert try_material_lock(brand) is True
    with db.connection() as observer:
        assert material_tasks.get(observer, db.DEV_ORG_ID, brand, campaign_id,
                                  task["id"])["revision"] == 1


def test_material_nested_rollback_releases_lock_and_discards_business_rows(campaign):
    brand, campaign_id, _, _ = campaign
    conn = db.current()
    conn.execute("SELECT 1")
    with conn.atomic():
        with pytest.raises(ValueError, match="rejected"):
            with conn.atomic():
                material_tasks.create(conn, db.DEV_ORG_ID, brand, campaign_id, {
                    "operation_id": "rollback-create", "title": "Material", "mode": "copy"
                }, "test")
                assert try_material_lock(brand) is False
                raise ValueError("rejected")
        assert try_material_lock(brand) is True
        assert conn.execute(
            "SELECT count(*) AS n FROM ads_material_task WHERE campaign_id=%s", (campaign_id,)
        ).fetchone()["n"] == 0
    conn.commit()
