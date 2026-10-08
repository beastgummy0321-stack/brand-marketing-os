/** Required server projections. Counts and applicability are computed by the backend. */
export interface LearningEvidence {
  schema_version: 1;
  id: string;
  meaning_revision: string;
  display_text: string;
  support_label: string;
  provenance: "platform_observation" | "user_report" | "operation_readback" | "simulation" | "unknown";
  sources: {kind: "campaign" | "pause" | "ab" | "settle" | "coordinate" | "visual" | null;
    id: string | null; version: string | null; period: {start: string | null; end: string | null}; label: string | null}[];
  scope: {product_id: string | null; product_label: string | null; audience_key: string | null;
    customer_group_id: string | null; claim_key: string | null;
    claim_family: "performance" | "brand_fact" | "operation" | null;
    objective_family: string | null; result_kind: string | null; currency: string | null; attribution: string | null};
  conditions: {price_version: string | null; offer_key: string | null; offer_version: string | null;
    material_version: string | null; target_version: string | null; valid_until: string | null};
  sample: {result_events: number | null; sufficient: boolean | null};
  independent_count: number;
  same_direction_count: number;
  contrary_count: number;
  use_state: "usable" | "history" | "revalidation" | "excluded";
  reason_codes: string[];
  reason_labels: string[];
  allowed_uses: ("test" | "retain_control" | "market_support" | "brand_fact" | "operation")[];
  limits: string[];
}

export interface LearningEvidenceContext {
  schema_version: 1;
  revision: string;
  scope_product_id: string | null;
  scope_label: string | null;
  eligible_count: number;
  items: LearningEvidence[];
  omitted: number;
}
