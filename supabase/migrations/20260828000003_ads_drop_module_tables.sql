-- supabase/migrations/20260828000003_ads_drop_module_tables.sql
-- Module: ads (removal)
-- Shell slice, ticket 3 (HANDOFF-shell-slice.md §4): app/ads/ was deleted in ticket 2, so
-- every table 20260826000004_ads_baseline.sql created is now unreachable from any code path.
-- Drops exactly those 44 tables and nothing else.
--
-- Checked before writing this file: no surviving table holds a foreign key into any of the 44
-- (pg_constraint query against the local DB returned zero rows), so CASCADE here cannot take a
-- live table's constraint with it. CASCADE is still used because the 44 reference each other.
--
-- NOT dropped, on purpose:
--   - cycle_shopee_code — created by the orders baseline, not this module. Its
--     campaign_cycle_id column is orphaned now and its accessors lost their last caller, but
--     it belongs to app/orders and orders_repo.BRAND_CASCADE_TABLES still lists it. Recorded
--     as follow-up debt; a migration that reaches into another module's tables is exactly the
--     boundary violation CLAUDE.md #7 forbids.
--   - learning_ledger, strategy_hypothesis — brand-permanent layer (see the ads baseline
--     file header: "learning_ledger is NOT created here").
--   - rule_card_value — app/core/rule_cards.py, still live.

DROP TABLE IF EXISTS
    activation_authorization,
    ad_account,
    ad_revenue_coefficient,
    ad_revenue_coefficient_error_log,
    adoption_decision,
    brand_checklist_item,
    campaign_activation,
    campaign_cycle,
    campaign_cycle_goal,
    campaign_cycle_hypothesis,
    campaign_cycle_product,
    campaign_plan,
    campaign_plan_option,
    channel_plan,
    channel_tracking_check,
    creative_brief,
    creative_rule_card,
    creative_theme,
    creative_theme_component,
    creative_variant,
    cycle_checklist_item,
    cycle_checkpoint,
    cycle_code_verification,
    cycle_voucher_code,
    derived_metric,
    discovered_campaign,
    experiment_cell,
    external_ad_mapping,
    final_asset,
    finding,
    ga4_summary,
    ga4_sync_status,
    marketing_goal,
    offer,
    performance_reading,
    performance_snapshot,
    publishing_package,
    reading_snapshot,
    reading_snapshot_input,
    recommendation,
    rule_dissent,
    settlement_version,
    success_criterion,
    task_card
CASCADE;
