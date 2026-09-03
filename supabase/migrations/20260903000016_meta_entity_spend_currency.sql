-- supabase/migrations/20260903000016_meta_entity_spend_currency.sql
-- Module: meta (ADR 0049). Ticket: T5. Decision of record: ADR 0057 section 4.
--
-- Why a column and not a join. brand_meta_ad_account is m:n, so one brand may bind accounts in
-- two currencies, and SUM(spend) across them adds two kinds of money together -- wrong, with no
-- error, which is the same failure mode roas's "NULL is never 0" rule exists to prevent.
-- Resolving the currency by joining meta_ad_account at READ time would answer "what currency was
-- this spend in" with the account's CURRENT setting: constitution rule 7, on the money path.
-- So it is frozen on the row, at write time, like every other fact in this table.
--
-- Every read that sums spend groups by currency and never adds across it (ADR 0057 section 4).
-- With one currency in play today that costs one GROUP BY; the day a tenant runs TWD and USD it
-- is the difference between one wrong number and two right ones.
--
-- Three statements, not one: the table holds rows (166 on 2026-09-03, all test data per
-- CLAUDE.md), so a NOT NULL column cannot be added in a single stroke without inventing a
-- default. There is no default to invent and none is wanted -- a guessed currency on a money row
-- is exactly the silent error above. The backfill is exact rather than guessed: meta_ad_account
-- .currency is itself NOT NULL and comes from Graph's /me/adaccounts `currency` field
-- (app/meta/graph.py list_ad_accounts), and every spend row already carries a mandatory FK to
-- the account it was pulled from.
ALTER TABLE meta_entity_spend ADD COLUMN currency text;

UPDATE meta_entity_spend mes
   SET currency = acc.currency
  FROM meta_ad_account acc
 WHERE acc.id = mes.ad_account_id;

ALTER TABLE meta_entity_spend ALTER COLUMN currency SET NOT NULL;
