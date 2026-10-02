import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/settingsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/settingsApi")>("@/lib/settingsApi");
  return { ...actual, fetchSettings: vi.fn() };
});
vi.mock("./ApiKeySection", () => ({ ApiKeySection: () => <p>AI 金鑰內容</p> }));
vi.mock("./SpendCapSection", () => ({ SpendCapSection: () => <p>品牌預算內容</p> }));
vi.mock("./ModelSection", () => ({
  ModelSection: () => <label>模型草稿<input aria-label="模型草稿" defaultValue="原始模型" /></label>,
}));
vi.mock("./MetaSection", () => ({ MetaSection: () => <p>廣告連線內容</p> }));
vi.mock("./RuleCardsSection", () => ({ RuleCardsSection: () => <p>規則內容</p> }));

import { fetchSettings, saveAiMonthlyCostLimit, type SettingsData } from "@/lib/settingsApi";
import { SettingsPage } from "./SettingsPage";

const mockFetchSettings = vi.mocked(fetchSettings);

const SETTINGS: SettingsData = {
  masked_key: null,
  api_key_source: null,
  db_key_present: false,
  model_choices: [],
  current_model: "model-a",
  task_model_thinking_table: [],
  intake_budget: 30,
  ai_key_source: "platform",
  ai_cap_applies: true,
  ai_monthly_spend: 0,
  ai_monthly_cost_limit: 20,
  is_owner: true,
};

function view(entry = "/settings") {
  mockFetchSettings.mockResolvedValue(SETTINGS);
  return render(<MemoryRouter initialEntries={[entry]}><SettingsPage /></MemoryRouter>);
}

afterEach(() => vi.clearAllMocks());

describe("SettingsPage 一般與進階層級", () => {
  it("預設顯示品牌 AI 費用上限與組織月費摘要，並把廣告連線留在常用設定", async () => {
    view();
    expect(await screen.findByText("品牌預算內容")).toBeTruthy();
    expect(screen.getByRole("button", { name: "品牌 AI 費用上限" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText(/已使用 US\$ 0\.00／上限 US\$ 20\.00/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "查看 AI 金鑰與月費" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Meta 廣告連線" })).toBeTruthy();
    expect(screen.getByText("進階設定").closest("details")?.open).toBe(false);
  });

  it("既有進階深連結會展開，切頁後仍保留已輸入但未儲存的草稿", async () => {
    view("/settings?tab=models");
    const draft = await screen.findByRole("textbox", { name: "模型草稿" });
    expect(screen.getByText("進階設定").closest("details")?.open).toBe(true);
    await userEvent.clear(draft);
    await userEvent.type(draft, "尚未儲存");

    await userEvent.click(screen.getByRole("button", { name: "品牌 AI 費用上限" }));
    await waitFor(() => expect(screen.getByText("品牌預算內容").closest("div")?.hidden).toBe(false));
    await userEvent.click(screen.getByRole("button", { name: "模型設定" }));
    expect(screen.getByRole("textbox", { name: "模型草稿" })).toHaveProperty("value", "尚未儲存");
  });
});

/** F47-I02 (drill-10 V2, `a-06-ai-limit-0-400.png`): every settings save throws the server's sentence. */
describe("settings saves show the server's sentence", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("AI monthly limit 0 → the server's sentence, not 「儲存失敗（狀態碼 400）」", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ error: "AI 月費上限請填大於 0 的數字，例如 200。" }), { status: 400 })),
    );
    await expect(saveAiMonthlyCostLimit(0)).rejects.toThrow("AI 月費上限請填大於 0 的數字，例如 200。");
  });

  it("a body without a sentence falls back to the status-code text", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("<html>bad gateway</html>", { status: 502 })));
    await expect(saveAiMonthlyCostLimit(200)).rejects.toThrow("儲存失敗（狀態碼 502）");
  });
});
