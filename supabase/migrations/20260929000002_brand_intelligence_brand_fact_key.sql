-- supabase/migrations/20260929000002_brand_intelligence_brand_fact_key.sql
-- Module: brand_intelligence. Ticket: F38-I01 (feature F38, decision 1).
--
-- A brand registers the evidence it really has as 「證據」 brand facts (fact_type 'proof').
-- `fact_key` names which of the six proof kinds the fact is -- exactly the six `proof`
-- coordinate keys. Other fact types keep NULL. Reader: app.brand_intelligence.repository
-- .available_proof_keys (feeds the ads and workbench prompt builders).
ALTER TABLE brand_fact ADD COLUMN fact_key text;
ALTER TABLE brand_fact ADD CONSTRAINT brand_fact_proof_key_valid
    CHECK (fact_type <> 'proof' OR fact_key IN ('customer_review', 'expert_endorsement', 'lab_report',
                                                'sales_numbers', 'media_coverage', 'founder_voice'));
ALTER TABLE brand_fact ADD CONSTRAINT brand_fact_key_only_for_proof
    CHECK (fact_type = 'proof' OR fact_key IS NULL);
