import { afterEach, expect, it, vi } from "vitest";
import { refreshExisting, syncCampaign } from "./adsExternalApi";

vi.mock("@/lib/auth", () => ({
  getAccessToken: vi.fn(async () => "fixture-token"),
  getOrgId: () => "fixture-org",
  setOrgId: vi.fn(),
  signOut: vi.fn(),
}));

afterEach(() => vi.unstubAllGlobals());

it("ordinary account retry preserves scope and optional dates through the actual HTTP client", async () => {
  const job = { id: "aes_1", status: "pending", last_success_at: null };
  const send = vi.fn<typeof fetch>(async () => new Response(JSON.stringify({ job }), { status: 200 }));
  vi.stubGlobal("fetch", send);

  expect(await refreshExisting("brand/a", "fixture", "account/b")).toEqual({ job });
  expect(send.mock.calls[0][0]).toBe("/api/ads/brands/brand%2Fa/existing-campaigns/refresh");
  expect(JSON.parse(String(send.mock.calls[0][1]?.body))).toEqual({
    platform: "fixture", source_account: "account/b",
  });
  const range = { start: "2026-11-02", end: "2026-11-04" };
  await refreshExisting("brand/a", "fixture", "account/b", range);
  expect(JSON.parse(String(send.mock.calls[1][1]?.body))).toEqual({
    platform: "fixture", source_account: "account/b", ...range,
  });
  const headers = new Headers(send.mock.calls[1][1]?.headers);
  expect(headers.get("Authorization")).toBe("Bearer fixture-token");
  expect(headers.get("X-Org-Id")).toBe("fixture-org");
  expect(send.mock.calls[1][1]?.method).toBe("POST");
});

it("ordinary campaign retry sends its existing body and retains every account job", async () => {
  const jobs = ["one", "two"].map(id => ({ id, status: "pending", last_success_at: null }));
  const receipt = { job: jobs[0], jobs };
  const send = vi.fn<typeof fetch>(async () => new Response(JSON.stringify(receipt), { status: 200 }));
  vi.stubGlobal("fetch", send);

  expect(await syncCampaign("brand/a", "campaign/b")).toEqual(receipt);
  expect(send).toHaveBeenCalledTimes(1);
  expect(send.mock.calls[0][0]).toBe("/api/ads/brands/brand%2Fa/campaigns/campaign%2Fb/sync");
  expect(send.mock.calls[0][1]?.method).toBe("POST");
  expect(send.mock.calls[0][1]?.body).toBe("{}");
});
