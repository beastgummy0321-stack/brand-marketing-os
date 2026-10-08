import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ChangeItem } from "@/lib/adsChangeApi";
import { CleanupVerifyRows } from "./CleanupVerifyRows";

vi.mock("@/components/layout/WorkspaceContext", () => ({ useWorkspace: () => ({
  identity: { org: { timezone: "Asia/Taipei", today: "2026-10-01" } },
}) }));

function item(overrides: Partial<ChangeItem> = {}): ChangeItem {
  return {
    id: "new_1", kind: "new_ad", target_id: "placement_1",
    target: { id: "placement_1", name: "New approved ad", platform: "fixture", source_account: "account_1", native_kind: "ad", native_id: "B2" },
    before: {}, after: {}, reason: "New proposition", verification_state: "confirmed",
    verification_label: "已核對相符", evidence_json: {}, reported_at: "2026-09-22T02:00:00Z",
    first_observed_at: null, verified_at: null, learning: {recorded: false, confidence: null, count: 0, evidence: null}, platform_url: null, ...overrides,
  };
}

describe("CleanupVerifyRows served proof", () => {
  it("keeps settings and each material proof distinct in a mixed set", async () => {
    render(<CleanupVerifyRows items={[item({ evidence_json: {
      observed_at: "2026-09-22T02:13:00Z", setting_matches: true,
      peers: [
        { handoff_item_id: "peer_1", entity_id: "entity_1", native_id: "B2", status: "confirmed", material_evidence: "media_verified" },
        { handoff_item_id: "peer_2", entity_id: "entity_2", native_id: "B3", status: "confirmed", material_evidence: "user_verified" },
        { handoff_item_id: "peer_3", entity_id: "entity_3", native_id: "B4", status: "confirmed", material_evidence: "unknown" },
      ],
    } }), item({ id: "pause_1", kind: "pause", target: { ...item().target, name: "Paused ad" },
      evidence_json: { observed_at: "2026-09-22T03:00:00Z" } })]} />);
    expect(screen.getByText(/讀回於.*10:13/)).toBeTruthy();
    expect(screen.getByText(/讀回於.*11:00/)).toBeTruthy();
    await userEvent.click(screen.getByText("核對資料"));
    expect(screen.getByText("平台素材已核對")).toBeTruthy();
    expect(screen.getByText("已人工核對素材")).toBeTruthy();
    expect(screen.getByText("素材尚未確認")).toBeTruthy();
    expect(screen.getAllByText("已核對相符")).toHaveLength(2);
  });

  it("labels the failed attempt and retained proof with their different times", async () => {
    render(<CleanupVerifyRows items={[item({ verification_state: "unknown", verification_label: "本次核對未完成",
      evidence_json: { observed_at: null, attempted_at: "2026-09-22T05:00:00Z",
        message: "本次讀回未完成；保留前次核對證據供查看，請稍後重試。",
        peers: [{ handoff_item_id: "peer_1", entity_id: "entity_1", status: "unknown", material_evidence: "unknown",
          previous_observation: { observed_at: "2026-09-22T02:13:00Z", evidence: { material_evidence: "user_verified" } } }],
      }, verified_at: "2026-09-22T06:00:00Z" })]} />);
    expect(screen.getByText(/本次嘗試於.*13:00/)).toBeTruthy();
    await userEvent.click(screen.getByText("核對資料"));
    expect(screen.getByText(/前次讀回於.*10:13/)).toBeTruthy();
    expect(screen.getByText("前次素材：已人工核對素材")).toBeTruthy();
    expect(screen.queryByText(/讀回於.*(13:00|14:00)/)).toBeNull();
  });

  it("never substitutes a legacy verified timestamp for a missing observation", () => {
    render(<CleanupVerifyRows items={[item({ verified_at: "2026-09-22T06:00:00Z",
      evidence_json: { observed_at: null, attempted_at: "2026-09-22T05:00:00Z" } })]} />);
    expect(screen.queryByText(/讀回於/)).toBeNull();
    expect(screen.queryByText(/尚未讀到/)).toBeNull();
    expect(screen.getByText("已核對相符")).toBeTruthy();
  });
});
