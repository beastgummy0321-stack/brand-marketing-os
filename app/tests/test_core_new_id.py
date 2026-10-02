"""app/tests/test_core_new_id.py — `db.new_id` sorts in creation order, also within one millisecond
(drill-10 fix: rows written in one transaction share `created_at`, so `ORDER BY created_at, id`
must follow creation order)."""

from unittest.mock import patch

from app.core import db


def test_ids_created_in_the_same_millisecond_sort_in_creation_order():
    with patch.object(db.time, "time_ns", return_value=1_790_000_000_000 * 1_000_000):
        ids = [db.new_id("ada") for _ in range(200)]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)


def test_a_later_millisecond_sorts_after():
    first = db.new_id("ada")
    future_ns = (db.time.time_ns() // 1_000_000 + 5) * 1_000_000
    with patch.object(db.time, "time_ns", return_value=future_ns):
        later = db.new_id("ada")
    assert later > first
