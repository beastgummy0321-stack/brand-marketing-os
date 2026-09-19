import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { IntakeCompletedPage } from "./IntakeCompletedPage";
import { fetchTruthCard, fetchPersonas } from "@/lib/intakeT2Api";
import { fetchLibrary } from "@/lib/libraryApi";
import { fetchLaunchReadiness } from "@/lib/adsLaunchApi";

vi.mock("@/lib/intakeT2Api", () => ({ fetchTruthCard: vi.fn(), fetchPersonas: vi.fn() }));
vi.mock("@/lib/libraryApi", () => ({ fetchLibrary: vi.fn() }));
vi.mock("@/lib/adsLaunchApi", () => ({ fetchLaunchReadiness: vi.fn() }));
vi.mock("@/components/ads", () => ({ ReadinessList: () => null }));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchTruthCard).mockResolvedValue({ accepted: [], needs_confirmation: [], forbidden: [] });
  vi.mocked(fetchPersonas).mockRejectedValue(new Error("選用資料暫不可用"));
  vi.mocked(fetchLaunchReadiness).mockRejectedValue(new Error("檢查暫不可用"));
});

describe("completed intake entry", () => {
  it.each(["has_history", "none"] as const)("history=%s does not gate current campaigns or the first plan", async (history) => {
    vi.mocked(fetchLibrary).mockResolvedValue({ brand: { advertising_history: history } } as Awaited<ReturnType<typeof fetchLibrary>>);
    render(<MemoryRouter><IntakeCompletedPage brandId="cold" onRestart={vi.fn()} /></MemoryRouter>);
    expect((await screen.findByRole("link", { name: "建立投放計畫" })).getAttribute("href")).toBe("/brands/cold/ads/new");
    expect(screen.getByRole("link", { name: "前往投放中心" }).getAttribute("href")).toBe("/brands/cold/ads");
    const historical = screen.queryByRole("link", { name: "回顧歷史投放（選用）" });
    if (history === "has_history") {
      expect(historical?.getAttribute("href")).toBe("/brands/cold/intake/history");
      expect(screen.getByText(/不會加入投放中心的目前活動/)).toBeTruthy();
    } else expect(historical).toBeNull();
  });
  it("keeps the ads entry available when the completed research summary cannot load", async () => {
    vi.mocked(fetchTruthCard).mockRejectedValue(new Error("暫時讀不到"));
    vi.mocked(fetchLibrary).mockRejectedValue(new Error("暫時讀不到"));
    render(<MemoryRouter><IntakeCompletedPage brandId="cold" onRestart={vi.fn()} /></MemoryRouter>);
    expect((await screen.findByRole("link", { name: "前往投放中心" })).getAttribute("href")).toBe("/brands/cold/ads");
    expect(screen.getByRole("button", { name: "重新讀取" })).toBeTruthy();
  });
});
