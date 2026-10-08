import {describe, expect, it} from "vitest";
import {citedEvidence, usedEvidence, unavailableCitations, unusedEvidence} from "./evidenceProjection";
import {evidenceFixture, strategyFixture} from "./strategyEvidence.fixtures";

describe("exact saved-decision citations", () => {
  it("does not mistake a usable planner input for an actual citation", () => {
    const c = strategyFixture(); const basis = c.budget_basis_json.basis!;
    const decision = c.budget_basis_json.strategy!.decision!;
    expect(citedEvidence(basis, decision).map(row => row.id)).toEqual(["current"]);
    expect(usedEvidence(basis, decision).map(row => row.id)).toEqual(["current"]);
    expect(unusedEvidence(basis, decision).map(row => row.id)).toEqual(["repeat", "changed"]);
  });
  it("deduplicates repeated exact learning refs and rejects same-ID non-learning refs", () => {
    const c = strategyFixture(); const basis = c.budget_basis_json.basis!;
    const decision = c.budget_basis_json.strategy!.decision!;
    decision.slots[1].evidence_refs = [{kind: "learning", id: "current"}, {kind: "result", id: "repeat"}];
    expect(citedEvidence(basis, decision).map(row => row.id)).toEqual(["current"]);
  });
  it("old plans without refs keep inputs in the unused projection", () => {
    const basis = strategyFixture().budget_basis_json.basis!;
    expect(citedEvidence(basis, undefined)).toEqual([]);
    expect(usedEvidence(basis, undefined)).toEqual([]);
    expect(unusedEvidence(basis, undefined)).toHaveLength(3);
  });
  it("finds an exact context-only learning ref without promoting non-learning refs", () => {
    const c = strategyFixture(); const basis = c.budget_basis_json.basis!;
    const decision = c.budget_basis_json.strategy!.decision!;
    basis.learnings = [];
    expect(usedEvidence(basis, decision).map(row => row.id)).toEqual(["current"]);
    expect(unusedEvidence(basis, decision).map(row => row.id)).toEqual(["repeat", "changed"]);
  });
  it("finds an exact ranked-only learning ref and deduplicates its retained context", () => {
    const c = strategyFixture(); const basis = c.budget_basis_json.basis!;
    const decision = c.budget_basis_json.strategy!.decision!;
    const evidence = evidenceFixture("coordinate-only");
    basis.learnings = []; basis.evidence_context.items = [];
    basis.ranked_learnings = {evidence_context: {...basis.evidence_context, items: []}, campaigns: [{
      campaign_id: "previous", campaign_name: "Previous", sell_way_id: "prd_fixture", start_date: null,
      end_date: null, closed_on: null, cap: 450, currency: "TWD", spend: 1000, sales: 10, cost_per_sale: 100,
      counts: {keep: 1, replace: 0}, rule_text: "Retained ranking", empty_reason: null,
      rows: [{evidence, learning_id: evidence.id, rank: 1, of: 1, ad_id: "original", ad_name: "Original",
        customer_group: null, coordinates: [], spend: 1000, sales: 10, cost_per_sale: 100,
        verdict: "keep", verdict_label: "留下", flags: []}],
    }], groups: [], next: null};
    decision.slots[0].evidence_refs = [{kind: "learning", id: evidence.id}];
    expect(usedEvidence(basis, decision).map(row => row.id)).toEqual([evidence.id]);
    expect(unusedEvidence(basis, decision)).toEqual([]);
    basis.evidence_context.items = [evidence];
    expect(usedEvidence(basis, decision)).toHaveLength(1);
    decision.slots[0].evidence_refs = [{kind: "result", id: "original"}, {kind: "learning", id: evidence.id},
      {kind: "result", id: "original"}];
    expect(citedEvidence(basis, decision).map(row => row.id)).toEqual([evidence.id]);
    expect(usedEvidence(basis, decision).map(row => row.id)).toEqual([evidence.id]);
    expect(unusedEvidence(basis, decision)).toEqual([]);
    decision.slots[0].evidence_refs = [{kind: "result", id: "original"}];
    expect(usedEvidence(basis, decision).map(row => row.id)).toEqual([evidence.id]);
    evidence.use_state = "history";
    evidence.allowed_uses = [];
    expect(citedEvidence(basis, decision).map(row => row.id)).toEqual([evidence.id]);
    expect(usedEvidence(basis, decision)).toEqual([]);
    expect(unavailableCitations(basis, decision).map(row => row.id)).toEqual([evidence.id]);
    expect(unusedEvidence(basis, decision)).toEqual([]);
    decision.slots[0].evidence_refs = [{kind: "result", id: evidence.id}];
    expect(citedEvidence(basis, decision)).toEqual([]);
  });
  it.each(["history", "revalidation", "excluded"] as const)("a citation cannot promote %s evidence", state => {
    const c = strategyFixture(); const basis = c.budget_basis_json.basis!;
    const decision = c.budget_basis_json.strategy!.decision!;
    basis.learnings[0].evidence.use_state = state;
    expect(citedEvidence(basis, decision)).toHaveLength(1);
    expect(usedEvidence(basis, decision)).toEqual([]);
    expect(unavailableCitations(basis, decision).map(row => row.id)).toEqual(["current"]);
    expect(unusedEvidence(basis, decision).map(row => row.id)).not.toContain("current");
  });
});
