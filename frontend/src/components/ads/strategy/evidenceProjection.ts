import type { StrategyBasis, StrategyDecision } from "@/lib/adsStrategyTypes";
import type { LearningEvidence } from "@/lib/adsLearningEvidence";

/** Retained evidence pool; no extra read, inference, or eligibility calculation. */
function evidencePool(basis: StrategyBasis | undefined): LearningEvidence[] {
  const seen = new Set<string>();
  return [...(basis?.learnings ?? []).flatMap(row => row.evidence ? [row.evidence] : []),
    ...(basis?.ranked_learnings?.campaigns ?? []).flatMap(campaign => campaign.rows.flatMap(row => row.evidence ? [row.evidence] : [])),
    ...(basis?.ranked_learnings?.evidence_context?.items ?? []),
    ...(basis?.evidence_context?.items ?? [])].filter(row => {
    if (seen.has(row.id)) return false;
    seen.add(row.id); return true;
  });
}

/** Result refs address the ranked ad, learning refs address the evidence itself. Names establish no identity. */
export function citedEvidence(basis: StrategyBasis | undefined, decision: StrategyDecision | undefined): LearningEvidence[] {
  const refs = (decision?.slots ?? []).flatMap(slot => slot.evidence_refs ?? []);
  const ids = new Set(refs.filter(ref => ref.kind === "learning").map(ref => ref.id));
  const resultIds = new Set(refs.filter(ref => ref.kind === "result").map(ref => ref.id));
  for (const campaign of basis?.ranked_learnings?.campaigns ?? []) {
    for (const row of campaign.rows) {
      if (row.evidence && resultIds.has(row.ad_id)) ids.add(row.evidence.id);
    }
  }
  return evidencePool(basis).filter(row => ids.has(row.id));
}

/** Presentation of the backend verdict; an actual citation cannot upgrade unavailable evidence. */
export function usedEvidence(basis: StrategyBasis | undefined, decision: StrategyDecision | undefined): LearningEvidence[] {
  return citedEvidence(basis, decision).filter(row => row.use_state === "usable" && row.allowed_uses.length > 0);
}

export function unavailableCitations(basis: StrategyBasis | undefined, decision: StrategyDecision | undefined): LearningEvidence[] {
  return citedEvidence(basis, decision).filter(row => row.use_state !== "usable" || row.allowed_uses.length === 0);
}

export function unusedEvidence(basis: StrategyBasis | undefined, decision: StrategyDecision | undefined): LearningEvidence[] {
  const citedIds = new Set(citedEvidence(basis, decision).map(row => row.id));
  return evidencePool(basis).filter(row => !citedIds.has(row.id));
}
