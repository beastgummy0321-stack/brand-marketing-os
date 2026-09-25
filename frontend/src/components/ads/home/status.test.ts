import { describe, expect, it } from "vitest";
import type { QueueProposal } from "@/lib/adsTriageApi";
import { cleanupAction } from "./status";

const cleanupSet = (status: QueueProposal["status"], verification_state: QueueProposal["verification_state"]): QueueProposal => ({
  kind: "cleanup", change_set_id: "cs_1", campaign_id: "cmp_1", status, verification_state,
  reason: null, revisit_at: null, multi: true,
});

describe("cleanupAction", () => {
  it("opens a multi-item cleanup set's own step page, never the campaign overview", () => {
    const base = "/brands/brd_1/ads/campaigns/cmp_1/changes/cs_1";
    expect(cleanupAction("brd_1", "cmp_1", cleanupSet("draft", "pending"), null)).toMatchObject({ label: "等你核准", href: `${base}/confirm` });
    expect(cleanupAction("brd_1", "cmp_1", cleanupSet("approved", "pending"), null)).toMatchObject({ label: "到平台完成", href: `${base}/handoff` });
    expect(cleanupAction("brd_1", "cmp_1", cleanupSet("approved", "reported"), null)).toMatchObject({ href: `${base}/verify` });
  });

  it("uses the row's own proposal link before any change set exists", () => {
    expect(cleanupAction("brd_1", "cmp_1", null, "/brands/brd_1/ads/campaigns/cmp_1/propose/cleanup/cmp_1"))
      .toMatchObject({ label: "看提議", href: "/brands/brd_1/ads/campaigns/cmp_1/propose/cleanup/cmp_1" });
  });
});
