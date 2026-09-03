-- Module: schedule (ADR 0049). Ticket: T3e.
-- ADR 0050 forbids a unique key on the node ALONE -- two periods may cover the same node on
-- overlapping days, and ADR 0053 section 4 resolves that at read time. A unique per
-- (period, node) is a different constraint and is required: without it a second press of the
-- bind button writes a second membership row for the same node in the same period, and that
-- node's spend is then counted twice inside one settlement.
CREATE UNIQUE INDEX period_node_membership_period_node_idx
    ON period_node_membership(org_id, brand_id, campaign_period_id, channel_id, node_key);
