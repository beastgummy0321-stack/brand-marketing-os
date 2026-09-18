"""Provider guard uses real model limits while tests never call real models."""

import pytest

from app.ads import asset_suggestion_policy as policy
from app.llm import pricing, providers


def test_known_haiku_context_ceiling():
    assert policy.ceiling("anthropic", "claude-haiku-4-5") == pytest.approx(0.22048)
    for model in ("claude-sonnet-5", "claude-opus-5", "unknown"):
        with pytest.raises(ValueError):
            policy.ceiling("anthropic", model)
    with pytest.raises(ValueError):
        policy.ceiling("other", "claude-haiku-4-5")


def test_codex_exception_and_task_defaults():
    assert policy.ceiling("codex_cli", "gpt-5.6-luna") == 0
    assert "訂閱額度" in policy.CODEX_NOTICE
    assert "無法保證" in policy.CODEX_NOTICE
    assert policy.OUTPUT_CHARS == 16384
    assert providers.TASK_DEFAULTS["ads_user_asset_suggestions"]["model"] is None
    assert providers.resolve_thinking(task_type="ads_user_asset_suggestions") == "low"


def test_current_sonnet_price_does_not_rewrite_historical_rows():
    assert pricing.calculate_cost("claude-sonnet-5", 1000000, 1000000) == 12
