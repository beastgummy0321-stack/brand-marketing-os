-- supabase/migrations/20261003000002_ads_placement_blocked_reasons.sql
-- Module: ads (F44-I04, drill-9 red #2). A slot's refused confirmation keeps why: the list of
-- Contract C details (`{"kind","text","terms"}`, `asset_suggestion_policy.detail`) the no-AI
-- confirmation returned for this revision, `wait` details left out. Writer:
-- `app/ads/slots.py::_confirm_if_ready`; reset to `[]` by
-- `asset_suggestions._apply_confirmation`; a new revision (`user_assets_repository.revise`)
-- starts empty through the default. Reader: `slots._planned_slot`, which turns a non-empty list
-- into `state: "blocked"`. `pending_reason` keeps its current use.

ALTER TABLE ads_asset_placement ADD COLUMN blocked_reasons jsonb NOT NULL DEFAULT '[]'::jsonb;
