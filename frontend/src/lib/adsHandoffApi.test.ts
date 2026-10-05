import { beforeEach, expect, it, vi } from "vitest";
import { ApiNetworkError, apiFetch, isRejected } from "./http";
import { assignPlannedMaterial, checkHandoff, createNewAdHandoff, getHandoff, getPlannedMaterials, reconsiderHandoff } from "./adsHandoffApi";
vi.mock("./http", async () => ({ ...await vi.importActual("./http"), apiFetch: vi.fn() }));
vi.mock("@/lib/auth", () => ({ getAccessToken: vi.fn(async () => null), getOrgId: () => null, setOrgId: vi.fn(), signOut: vi.fn() }));
beforeEach(() => vi.clearAllMocks());
it("encodes scope and propagates abort signals to handoff requests", async () => {
  vi.mocked(apiFetch).mockResolvedValue(new Response(JSON.stringify({ items: [] }), { status: 200 }));
  const controller = new AbortController();
  await getHandoff("brand/a", "campaign/b", controller.signal);
  expect(apiFetch).toHaveBeenCalledWith("/api/ads/brands/brand%2Fa/campaigns/campaign%2Fb/handoff", expect.objectContaining({ method: "GET", signal: controller.signal }));
});
it("keeps check and disabled-ad reconsideration as distinct endpoints", async () => {
  vi.mocked(apiFetch).mockImplementation(async () => new Response(JSON.stringify({ item: { id: "h" } }), { status: 200 }));
  await checkHandoff("b", "c", "h", { platform: "fixture", source_account: "a", native_kind: "ad", native_id: "B2", user_verified: false });
  expect(apiFetch).toHaveBeenLastCalledWith(expect.stringContaining("/handoff/h/check"), expect.objectContaining({ method: "POST", body: expect.stringContaining('"user_verified":false') }));
  await reconsiderHandoff("b", "c", "h", "已停用");
  expect(apiFetch).toHaveBeenLastCalledWith(expect.stringContaining("/handoff/h/reconsider"), expect.objectContaining({ body: '{"reason":"已停用"}' }));
});
it("distinguishes a definitive rejection from an unknown server result", async () => {
  const payload = { operation_id: "op", title: "B2", month: "2026-09", placement_id: "p", revision: 1, destination_entity_id: "g", reason: "test" };
  vi.mocked(apiFetch).mockResolvedValueOnce(new Response(JSON.stringify({ error: { code: "handoff_unavailable", message: "版本失效" } }), { status: 409 }));
  const rejected = await createNewAdHandoff("b", "c", payload).catch(e => e);
  expect(isRejected(rejected, "handoff_unavailable")).toBe(true);
  expect(rejected.message).toBe("版本失效");
  vi.mocked(apiFetch).mockResolvedValueOnce(new Response("down", { status: 503 }));
  const error = await createNewAdHandoff("b", "c", payload).catch(e => e);
  expect(error).toBeInstanceOf(Error);
  expect(isRejected(error)).toBe(false);
  expect(error.message).toBe("尚未收到可確認的結果，請沿用原操作重試。");
});
it("uses the planned-ad assignment contract and a null pair for unlinking", async () => {
  vi.mocked(apiFetch).mockImplementation(async () => new Response(JSON.stringify({ planned_ads: [], ready_placements: [] }), { status: 200 }));
  await getPlannedMaterials("b", "c");
  expect(apiFetch).toHaveBeenLastCalledWith("/api/ads/brands/b/campaigns/c/launch-materials", expect.objectContaining({ method: "GET" }));
  await assignPlannedMaterial("b", "c", "ad/1", { placement_id: null, revision: null });
  expect(apiFetch).toHaveBeenLastCalledWith("/api/ads/brands/b/campaigns/c/launch-materials/ad%2F1", expect.objectContaining({ method: "PUT", body: '{"placement_id":null,"revision":null}' }));
});
it("an ads write that never got an answer shows the shared write sentence (F51 Contract H)", async () => {
  const actual = await vi.importActual<typeof import("./http")>("./http");
  vi.mocked(apiFetch).mockImplementationOnce(actual.apiFetch);
  vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
  try {
    const payload = { operation_id: "op", title: "B2", month: "2026-09", placement_id: "p", revision: 1, destination_entity_id: "g", reason: "test" };
    const error = await createNewAdHandoff("b", "c", payload).catch(e => e);
    expect(error).toBeInstanceOf(ApiNetworkError);
    expect(error.message).toBe(new ApiNetworkError(true).message);
    expect(error.message).not.toContain("Failed to fetch");
  } finally {
    vi.unstubAllGlobals();
  }
});
