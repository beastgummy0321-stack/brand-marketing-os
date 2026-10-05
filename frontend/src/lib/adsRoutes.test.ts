import { expect, it } from "vitest";
import { campaignPath, campaignFlowPath, newCampaignPath, WORKSPACE_TABS } from "./adsRoutes";
it("encodes IDs and query values once with canonical tabs", () => {
  expect(campaignPath("b /", "c?", { tab: "perf", ad: "a&b" })).toBe("/brands/b%20%2F/ads/campaigns/c%3F?tab=perf&ad=a%26b");
  expect(WORKSPACE_TABS).toContain("perf");
  expect(WORKSPACE_TABS).not.toContain("performance");
  for (const tab of WORKSPACE_TABS) expect(campaignPath("b", "c", { tab })).toBe(`/brands/b/ads/campaigns/c?tab=${tab}`);
});
it("builds flow, review, settle, wait, publish and new destinations", () => {
  for (const parts of [["changes", "s", "confirm"], ["review", "a"], ["reviews", "r", "prepare"], ["settle"], ["wait"], ["publish"]]) {
    expect(campaignFlowPath("b", "c", parts)).toBe(`/brands/b/ads/campaigns/c/${parts.join("/")}`);
  }
  expect(campaignFlowPath("b", "c", ["propose", "pause", "a/1"], { from: "perf", ref: undefined })).toBe("/brands/b/ads/campaigns/c/propose/pause/a%2F1?from=perf");
  expect(newCampaignPath("b/1", { product: "x y" })).toBe("/brands/b%2F1/ads/new?product=x+y");
});
