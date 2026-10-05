import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/settingsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/settingsApi")>("@/lib/settingsApi");
  return {
    ...actual,
    fetchBrandOptions: vi.fn(),
    fetchRuleCards: vi.fn(),
    saveRuleCard: vi.fn(),
    resetRuleCard: vi.fn(),
  };
});

import { ApiResponseError } from "@/lib/http";
import { fetchBrandOptions, fetchRuleCards, resetRuleCard, saveRuleCard, type RuleCard } from "@/lib/settingsApi";
import { RuleCardsSection } from "./RuleCardsSection";

const mockFetchBrands = vi.mocked(fetchBrandOptions);
const mockFetchCards = vi.mocked(fetchRuleCards);
const mockReset = vi.mocked(resetRuleCard);

function card(value: number, customized = false): RuleCard {
  return {
    key: "spend",
    title: "花費護欄",
    description: "控制品牌花費判讀",
    fields: [{ key: "minimum", label: "最低花費", unit: "US$", help: "低於此值先觀察", value, customized }],
  };
}

afterEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("RuleCardsSection 規則卡範圍與重設", () => {
  it("清楚顯示作用品牌、欄位單位，且切換品牌不會沿用另一品牌的草稿", async () => {
    mockFetchBrands.mockResolvedValue([
      { brand_id: "a", brand_name: "甲品牌" },
      { brand_id: "b", brand_name: "乙品牌" },
    ]);
    mockFetchCards.mockImplementation(async (brandId) => ({ brand_id: brandId, cards: [card(brandId === "a" ? 10 : 20)] }));
    render(<RuleCardsSection />);

    await userEvent.selectOptions(await screen.findByLabelText("選擇品牌"), "a");
    expect(await screen.findByText("甲品牌", { selector: "span" })).toBeTruthy();
    const input = screen.getByRole("spinbutton", { name: /最低花費/ });
    expect(input).toHaveProperty("value", "10");
    expect(screen.getByText("US$")).toBeTruthy();
    await userEvent.clear(input);
    await userEvent.type(input, "999");

    await userEvent.selectOptions(screen.getByLabelText("選擇品牌"), "b");
    await waitFor(() => expect(screen.getByRole("spinbutton", { name: /最低花費/ })).toHaveProperty("value", "20"));
    expect(screen.getByText("乙品牌", { selector: "span" })).toBeTruthy();
  });

  it("把整張卡重設寫在按鈕與確認訊息，並沿用既有 reset API", async () => {
    mockFetchBrands.mockResolvedValue([{ brand_id: "a", brand_name: "甲品牌" }]);
    mockFetchCards.mockResolvedValue({ brand_id: "a", cards: [card(10, true)] });
    mockReset.mockResolvedValue(card(5));
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<RuleCardsSection />);

    await userEvent.selectOptions(await screen.findByLabelText("選擇品牌"), "a");
    await userEvent.click(await screen.findByRole("button", { name: "重設整張卡" }));
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("重設整張「花費護欄」"));
    await waitFor(() => expect(mockReset).toHaveBeenCalledWith("a", "spend"));
    expect(screen.getByRole("spinbutton", { name: /最低花費/ })).toHaveProperty("value", "5");
  });

  /** F47-I02 (drill-10 V2, `a-08-rulecard-0-400.png`): a refused save shows the server's sentence,
   * not 「規則卡儲存失敗（狀態碼 400）」. Runs the real `saveRuleCard` against a stubbed 400. */
  it("a refused save shows the server's sentence", async () => {
    const actual = await vi.importActual<typeof import("@/lib/settingsApi")>("@/lib/settingsApi");
    vi.mocked(saveRuleCard).mockImplementation(actual.saveRuleCard);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({ error: "有欄位沒有填一個大於 0 的數字。", field_errors: { minimum: "請填一個大於 0 的數字。" } }),
          { status: 400 },
        ),
      ),
    );
    mockFetchBrands.mockResolvedValue([{ brand_id: "a", brand_name: "甲品牌" }]);
    mockFetchCards.mockResolvedValue({ brand_id: "a", cards: [card(10)] });
    render(<RuleCardsSection />);

    await userEvent.selectOptions(await screen.findByLabelText("選擇品牌"), "a");
    const input = await screen.findByRole("spinbutton", { name: /最低花費/ });
    await userEvent.clear(input);
    await userEvent.type(input, "0");
    await userEvent.click(screen.getByRole("button", { name: "儲存這張卡" }));
    expect(await screen.findByText("有欄位沒有填一個大於 0 的數字。")).toBeTruthy();
    expect(screen.queryByText(/狀態碼/)).toBeNull();
  });

  /** F47-I03 (drill-10 甲 設定 #24–#32, `a-09-margin-7-accepted.png`): each field shows its own
   * `field_errors` sentence under it (a pair error under both), the typed value stays, an empty field
   * is not sent as 0, and the sentences clear once a field changes. */
  it("shows each refused field's own sentence under it and clears it on edit", async () => {
    const pair: RuleCard = {
      key: "plan_count",
      title: "檔期方案數量上下限",
      description: "",
      fields: [
        { key: "min", label: "下限", unit: "個", help: "", value: 1, customized: false },
        { key: "max", label: "上限", unit: "個", help: "", value: 5, customized: false },
        { key: "margin", label: "毛利率", unit: "%", help: "例如填 70 代表毛利 70%", value: 45, customized: false },
      ],
    };
    const sentence = "下限（6）不能大於上限（3）。";
    vi.mocked(saveRuleCard).mockRejectedValue(
      new ApiResponseError(sentence, 400, { min: sentence, max: sentence, margin: "毛利率要大於 0、小於 100（例如填 70 代表毛利 70%）。" }),
    );
    mockFetchBrands.mockResolvedValue([{ brand_id: "a", brand_name: "甲品牌" }]);
    mockFetchCards.mockResolvedValue({ brand_id: "a", cards: [pair] });
    render(<RuleCardsSection />);

    await userEvent.selectOptions(await screen.findByLabelText("選擇品牌"), "a");
    const min = await screen.findByRole("spinbutton", { name: /下限/ });
    await userEvent.clear(min);
    await userEvent.type(min, "6");
    const max = screen.getByRole("spinbutton", { name: /上限/ });
    await userEvent.clear(max);
    await userEvent.type(max, "3");
    const margin = screen.getByRole("spinbutton", { name: /毛利率/ });
    await userEvent.clear(margin);
    await userEvent.click(screen.getByRole("button", { name: "儲存這張卡" }));

    await waitFor(() => expect(screen.getAllByRole("alert")).toHaveLength(3));
    expect(min.closest("label")?.textContent).toContain(sentence);
    expect(max.closest("label")?.textContent).toContain(sentence);
    expect(margin.closest("label")?.textContent).toContain("毛利率要大於 0、小於 100（例如填 70 代表毛利 70%）。");
    // What was typed is sent as typed; the emptied margin is left out (never 0).
    expect(vi.mocked(saveRuleCard)).toHaveBeenCalledWith("a", "plan_count", { min: "6", max: "3" });
    expect(min).toHaveProperty("value", "6");

    await userEvent.type(margin, "60");
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
  });
});
