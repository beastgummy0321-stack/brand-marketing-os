import { afterEach, expect, it, vi } from "vitest";
import { adoptStrategy } from "./adsApi";

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
