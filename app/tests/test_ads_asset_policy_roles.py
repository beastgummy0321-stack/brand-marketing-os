"""Asset evidence and generation policies must never apply to anonymous roles."""

from app.core import db


def test_asset_policies_are_authenticated_only():
    tables = {
        "ads_asset_suggestion_batch",
        "ads_asset_suggestion_reservation",
        "ads_asset_binding",
        "ads_asset_observation_claim",
    }
    rows = db.current().execute(
        "SELECT tablename, roles, qual, with_check FROM pg_policies "
        "WHERE schemaname=current_schema() AND tablename=ANY(%s)",
        (sorted(tables),),
    ).fetchall()
    assert {row["tablename"] for row in rows} == tables
    for row in rows:
        assert set(row["roles"]) == {"authenticated"}, row["tablename"]
        assert "app.org_id" in row["qual"], row["tablename"]
        assert "app.org_id" in row["with_check"], row["tablename"]
