"""Persona notification routes to the readable/editable section."""
from unittest.mock import MagicMock, patch

from app.intake import persona_generation


def test_persona_notification_destination():
    with patch.object(persona_generation.background_job, "notify") as notify:
        persona_generation._notify(MagicMock(), "brand", "人物誌好了")
    assert notify.call_args.kwargs["action_url"] == "/app/brands/brand/library?tab=customer-voice"


def test_failed_persona_is_not_announced_as_success():
    conn = MagicMock()
    with (patch.object(persona_generation, "core_db_connection") as connection,
          patch.object(persona_generation.repo, "get_brand", return_value={"name": "Test"}),
          patch.object(persona_generation, "generate", return_value=(False, "bad shape")),
          patch.object(persona_generation, "_notify") as notify):
        connection.return_value.__enter__.return_value = conn
        persona_generation.background_intake_persona("org", "brand")
    assert "失敗" in notify.call_args.args[2]
