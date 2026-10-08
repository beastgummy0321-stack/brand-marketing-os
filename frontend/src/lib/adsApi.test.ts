import { afterEach, expect, it, vi } from "vitest";
import { adoptStrategy } from "./adsApi";
import { createCampaignFromPicks, getNextPeriod } from "./adsWizardApi";

vi.mock("@/lib/auth", () => ({
  getAccessToken: vi.fn(async () => "fixture-token"),
  getOrgId: () => "fixture-org",
  setOrgId: vi.fn(),
  signOut: vi.fn(),
}));

afterEach(() => vi.unstubAllGlobals());

it("sends the displayed strategy approval as JSON through the real HTTP client", async () => {
  const campaign = { id: "campaign/b", status: "ready" };
  const send = vi.fn<typeof fetch>(async () => new Response(JSON.stringify({ campaign }), { status: 200 }));
  vi.stubGlobal("fetch", send);
  const approval = { expected_revision: "displayed-revision", operation_id: "stable-operation" };

  expect(await adoptStrategy("brand/a", "campaign/b", approval)).toEqual(campaign);
  expect(send).toHaveBeenCalledTimes(1);
  const [url, init] = send.mock.calls[0];
  expect(url).toBe("/api/ads/brands/brand%2Fa/campaigns/campaign%2Fb/plan");
  expect(init?.method).toBe("POST");
  const headers = new Headers(init?.headers);
  expect(headers.get("Content-Type")).toBe("application/json");
  expect(headers.get("Authorization")).toBe("Bearer fixture-token");
  expect(headers.get("X-Org-Id")).toBe("fixture-org");
  expect(JSON.parse(String(init?.body))).toEqual(approval);
});


it("reads exact completed-month sources without a write request", async () => {
  const preparation = { month: "2026-09", revision: "source-revision", source_campaigns: [],
    eligible_learning_refs: [], excluded: [{ owner: "campaign", ref: "oversize", reason_code: "source_scope_too_large" }] };
  const send = vi.fn<typeof fetch>(async () => new Response(JSON.stringify(preparation), { status: 200 }));
  vi.stubGlobal("fetch", send);
  expect(await getNextPeriod("brand/a", "2026-09")).toEqual(preparation);
  expect(send.mock.calls[0][0]).toBe("/api/ads/brands/brand%2Fa/next-period?month=2026-09");
  expect(send.mock.calls[0][1]?.body).toBeUndefined();
});

it("keeps continuation identity and explicit association in structured create", async () => {
  const send = vi.fn<typeof fetch>(async () => new Response(JSON.stringify({ campaign: { id: "draft" } }), { status: 200 }));
  vi.stubGlobal("fetch", send);
  const picks = { product_ids: ["sell-way"] as [string], objective: "購買", budget: 7000,
    continuation: { month: "2026-09", campaign_ids: ["native-source"], revision: "source-revision",
      request_id: "82416fd4-63d1-4ccf-8806-477fc16545e9", product_mapping_confirmed: true } };
  await createCampaignFromPicks("brand/a", picks);
  expect(JSON.parse(String(send.mock.calls[0][1]?.body))).toEqual(picks);
});
