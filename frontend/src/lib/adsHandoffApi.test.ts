import { beforeEach, expect, it, vi } from "vitest";
import { apiFetch } from "./http";
import { assignPlannedMaterial, checkHandoff, createNewAdHandoff, getHandoff, getPlannedMaterials, HandoffRequestRejected, reconsiderHandoff } from "./adsHandoffApi";
vi.mock("./http", async () => ({ ...await vi.importActual("./http"), apiFetch: vi.fn() }));
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
  vi.mocked(apiFetch).mockResolvedValueOnce(new Response(JSON.stringify({ error: { message: "版本失效" } }), { status: 409 }));
  await expect(createNewAdHandoff("b", "c", payload)).rejects.toBeInstanceOf(HandoffRequestRejected);
  vi.mocked(apiFetch).mockResolvedValueOnce(new Response("down", { status: 503 }));
  const error = await createNewAdHandoff("b", "c", payload).catch(e => e);
  expect(error).toBeInstanceOf(Error);
  expect(error).not.toBeInstanceOf(HandoffRequestRejected);
});
it("uses the planned-ad assignment contract and a null pair for unlinking", async () => {
  vi.mocked(apiFetch).mockImplementation(async () => new Response(JSON.stringify({ planned_ads: [], ready_placements: [] }), { status: 200 }));
  await getPlannedMaterials("b", "c");
  expect(apiFetch).toHaveBeenLastCalledWith("/api/ads/brands/b/campaigns/c/launch-materials", expect.objectContaining({ method: "GET" }));
  await assignPlannedMaterial("b", "c", "ad/1", { placement_id: null, revision: null });
  expect(apiFetch).toHaveBeenLastCalledWith("/api/ads/brands/b/campaigns/c/launch-materials/ad%2F1", expect.objectContaining({ method: "PUT", body: '{"placement_id":null,"revision":null}' }));
});
