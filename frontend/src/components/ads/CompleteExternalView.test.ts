import { beforeEach, expect, it, vi } from "vitest";
import { apiFetch } from "@/lib/http";
import { completeExternalView, type ExternalView } from "@/lib/adsExternalApi";

vi.mock("@/lib/http", async () => ({ ...(await vi.importActual<typeof import("@/lib/http")>("@/lib/http")), apiFetch: vi.fn() }));
const page = (overrides: Partial<ExternalView> = {}): ExternalView => ({
  entities: [], observations: [], next_entity_cursor: null, next_observation_cursor: null,
  window: { start: "2026-08-20", end: "2026-09-18" }, connections: [], sync: {}, coverage: {}, ...overrides,
});
beforeEach(() => vi.resetAllMocks());
it("loads both independent cursors in a fixed window before returning", async () => {
  vi.mocked(apiFetch)
    .mockResolvedValueOnce(new Response(JSON.stringify(page({ next_entity_cursor: "e2", next_observation_cursor: "o2" }))))
    .mockResolvedValueOnce(new Response(JSON.stringify(page({ next_observation_cursor: "ignored", connections: [{ platform: "meta", source_account: "1", state: "connected" }] }))))
    .mockResolvedValueOnce(new Response(JSON.stringify(page())));
  const result = await completeExternalView("brand", "campaign");
  expect(apiFetch).toHaveBeenCalledTimes(3);
  expect(String(vi.mocked(apiFetch).mock.calls[1][0])).toContain("entity_cursor=e2");
  expect(String(vi.mocked(apiFetch).mock.calls[2][0])).toContain("observation_cursor=o2");
  expect(String(vi.mocked(apiFetch).mock.calls[2][0])).toContain("start=2026-08-20");
  expect(result.next_entity_cursor).toBeNull();
  expect(result.next_observation_cursor).toBeNull();
  expect(result.connections).toHaveLength(1);
});
it("fails rather than presenting partial totals if a later page fails", async () => {
  vi.mocked(apiFetch).mockResolvedValueOnce(new Response(JSON.stringify(page({ next_observation_cursor: "o2" }))))
    .mockRejectedValueOnce(new Error("page failed"));
  await expect(completeExternalView("brand", "campaign")).rejects.toThrow("page failed");
});
it("rejects a repeated cursor instead of looping forever", async () => {
  vi.mocked(apiFetch).mockImplementation(async () => new Response(JSON.stringify(page({ next_entity_cursor: "same" }))));
  await expect(completeExternalView("brand", "campaign")).rejects.toThrow("分頁重複");
  expect(apiFetch).toHaveBeenCalledTimes(2);
});
