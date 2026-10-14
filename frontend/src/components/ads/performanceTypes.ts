export interface ResultEvidence {
  result_kind: string | null;
  result_label: string;
  result_action: string | null;
  result_attribution: string | null;
  currency: string | null;
  spend: number | null;
  count: number | null;
  known_count: number | null;
  cost_per_result: number | null;
  state: "known_positive" | "known_zero" | "incomplete" | "incompatible" | "unconfigured";
  data_state: ResultEvidence["state"];
  comparison_state: "ready" | "unconfigured" | "incompatible" | "unknown";
  reasons: string[];
  target: { value: number | null; basis: string | null; result_kind: string | null; revision: number | null };
  sample: { count: number | null; result_kind: string | null; days: number | null;
    days_present: number; days_known: number; derived_zero_days: number };
  evidence_refs: string[];
  evidence_ref_count: number;
  evidence_refs_omitted: number;
}
