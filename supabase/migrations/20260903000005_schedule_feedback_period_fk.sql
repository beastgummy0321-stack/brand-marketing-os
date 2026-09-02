-- supabase/migrations/20260903000005_schedule_feedback_period_fk.sql
-- Module: schedule (ADR 0049). Ticket T2b (docs/issues/t2b-period-screen/ticket.md), ADR 0053.
--
-- feedback.campaign_period_id has had no FK since T1b created it (20260901000002, comment:
-- "FK added by T2; campaign_period does not exist yet"). T2a created campaign_period
-- (20260903000001); this is the FK T1b left waiting. Nothing writes feedback with
-- scope='period' yet -- this is the constraint, not the feature.
ALTER TABLE feedback ADD FOREIGN KEY (campaign_period_id) REFERENCES campaign_period(id);
