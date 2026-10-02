import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchBrandReport, generateBrandReport, type BrandReportResponse } from "@/lib/brandReportApi";
import { BrandReportPage } from "./BrandReportPage";

vi.mock("@/lib/brandReportApi", () => ({ fetchBrandReport: vi.fn(), generateBrandReport: vi.fn() }));

const READY: BrandReportResponse = {
  report: {
    generated_at: "2026-10-01T13:00:00Z",
    brand_version: 7,
    model: "claude-opus-5",
    source_fact_count: 12,
    cost: 3.2,
    staleness: null,
    thin_data: false,
    sections: [
      { label: "品牌定位", summary: "給上班族的提神軟糖。", points: ["咖啡因 80mg"] },
      { label: "市場與競爭觀察", summary: "競品多以飲料為主。", points: [] },
    ],
  },
  job: { status: "idle" },
};

beforeEach(() => {
  vi.mocked(fetchBrandReport).mockReset();
  vi.mocked(generateBrandReport).mockReset();
});

function renderPage() {
  render(<MemoryRouter><BrandReportPage brandId="b1" /></MemoryRouter>);
}

describe("BrandReportPage regenerate failure (F47-I03, drill-10 甲 報告 #4)", () => {
  it("a refused regenerate keeps the report and says why inline with 「稍後再試」", async () => {
    vi.mocked(fetchBrandReport).mockResolvedValue(READY);
    vi.mocked(generateBrandReport).mockRejectedValueOnce(new Error("剛剛才生成過，兩分鐘後再試。"));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "重新生成報告" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("剛剛才生成過，兩分鐘後再試。");
    expect(screen.queryByText("讀取失敗")).toBeNull();
    expect(screen.getByText("給上班族的提神軟糖。")).toBeTruthy();

    vi.mocked(generateBrandReport).mockResolvedValueOnce(undefined);
    fireEvent.click(screen.getByRole("button", { name: "稍後再試" }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(generateBrandReport).toHaveBeenCalledTimes(2);
  });

  it("a failed re-read after the report is on screen keeps the report", async () => {
    vi.mocked(fetchBrandReport).mockResolvedValueOnce(READY).mockRejectedValueOnce(new Error("伺服器忙碌中。"));
    vi.mocked(generateBrandReport).mockResolvedValue(undefined);
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "重新生成報告" }));
    expect((await screen.findByRole("alert")).textContent).toContain("伺服器忙碌中。");
    expect(screen.getByText("給上班族的提神軟糖。")).toBeTruthy();
  });

  it("the whole-page 「讀取失敗」 is only for a first load with nothing to show", async () => {
    vi.mocked(fetchBrandReport).mockRejectedValue(new Error("伺服器忙碌中。"));
    renderPage();
    expect(await screen.findByText("讀取失敗")).toBeTruthy();
  });
});
