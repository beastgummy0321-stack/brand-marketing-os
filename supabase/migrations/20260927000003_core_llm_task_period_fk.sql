-- F31-I09 (item 13): llm_task is kept on brand delete on purpose (AI spend record), but its
-- campaign_period_id FK (NO ACTION since 20260905000003) blocked deleting the brand's periods.
-- The kept row forgets the period instead: ON DELETE SET NULL on the period column only
-- (org_id stays NOT NULL; column-list SET NULL needs Postgres 15+).
ALTER TABLE llm_task DROP CONSTRAINT llm_task_campaign_period_id_org_id_fkey;
ALTER TABLE llm_task
    ADD CONSTRAINT llm_task_campaign_period_id_org_id_fkey
    FOREIGN KEY (campaign_period_id, org_id) REFERENCES campaign_period(id, org_id)
    ON DELETE SET NULL (campaign_period_id);
