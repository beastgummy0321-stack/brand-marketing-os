-- A monthly envelope is not an additional spending authorization or a platform limit.
CREATE TABLE ads_month_budget (
 id text PRIMARY KEY,
 org_id text NOT NULL REFERENCES organisation(id),
 brand_id text NOT NULL REFERENCES brand(id),
 month date NOT NULL CHECK (extract(day FROM month)=1),
 currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
 amount numeric(18,2) NOT NULL CHECK (amount >= 0),
 revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
 confirmed_by text NOT NULL,
 confirmed_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(org_id,brand_id,month)
);
ALTER TABLE ads_month_budget ENABLE ROW LEVEL SECURITY;
GRANT SELECT,INSERT,UPDATE,DELETE ON ads_month_budget TO authenticated;
CREATE POLICY ads_month_budget_org_isolation ON ads_month_budget FOR ALL TO authenticated
 USING(org_id=current_setting('app.org_id',true)) WITH CHECK(org_id=current_setting('app.org_id',true));
