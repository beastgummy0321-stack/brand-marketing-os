"""Persona notification routes to the readable/editable section."""

from unittest.mock import MagicMock, patch

from app.intake import persona_generation


def test_persona_notification_destination():
    with patch.object(persona_generation.background_job, "notify") as notify:
        persona_generation._notify(MagicMock(), "brand", "人物誌好了")
    assert notify.call_args.kwargs["action_url"] == "/app/brands/brand/library?tab=customer-voice"


def test_failed_persona_is_not_announced_as_success():
    conn = MagicMock()
    with (
        patch.object(persona_generation, "core_db_connection") as connection,
        patch.object(persona_generation.repo, "get_brand", return_value={"name": "Test"}),
        patch.object(persona_generation, "generate", return_value=(False, "bad shape")),
        patch.object(persona_generation, "_notify") as notify,
    ):
        connection.return_value.__enter__.return_value = conn
        persona_generation.background_intake_persona("org", "brand")
    assert "失敗" in notify.call_args.args[2]


def test_persona_post_processing_failure_notifies_then_ends_the_job_failed():
    """F31-I02 (Contract J): red on master, where the exception was swallowed and the job
    ended `succeeded` although no personas were saved."""
    import pytest

    conn = MagicMock()
    with (
        patch.object(persona_generation, "core_db_connection") as connection,
        patch.object(persona_generation.repo, "get_brand", return_value={"name": "Test"}),
        patch.object(persona_generation, "generate", side_effect=RuntimeError("save failed")),
        patch.object(persona_generation, "_notify") as notify,
    ):
        connection.return_value.__enter__.return_value = conn
        with pytest.raises(RuntimeError, match="save failed"):
            persona_generation.background_intake_persona("org", "brand")
    assert "失敗" in notify.call_args.args[2]


def test_persona_state_follows_the_newest_job_before_llm_task_rows():
    """F31-I02 (Contract J): a queued job reads running even behind an older succeeded row;
    a failed job with no llm_task error reads failed with the worker hint."""
    from datetime import UTC, datetime

    from app.background import JOB_FAILED_MESSAGE

    old_ok = {"status": "succeeded", "started_at": datetime(2026, 9, 1, tzinfo=UTC),
              "error": None, "structured_output_json": None}
    with (
        patch.object(persona_generation, "_latest_task_row", return_value=old_ok),
        patch.object(persona_generation, "background_job_outcome", return_value="active"),
    ):
        assert persona_generation.generation_state("brand")["status"] == "running"
    with (
        patch.object(persona_generation, "_latest_task_row", return_value=None),
        patch.object(persona_generation, "background_job_outcome", return_value="failed"),
    ):
        state = persona_generation.generation_state("brand")
    assert state["status"] == "failed"
    assert state["error"] == JOB_FAILED_MESSAGE
