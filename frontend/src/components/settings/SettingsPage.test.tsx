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
    expect(screen.getByText(/已使用 0\.00 美元／上限 20\.00 美元/)).toBeTruthy();
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
    await expect(saveAiMonthlyCostLimit("0")).rejects.toThrow("AI 月費上限請填大於 0 的數字，例如 200。");
  });

  it("a body without a sentence falls back to the status-code text", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("<html>bad gateway</html>", { status: 502 })));
    await expect(saveAiMonthlyCostLimit("200")).rejects.toThrow("儲存失敗（狀態碼 502）");
  });
});

/** F50-I02 (Contract I; controls a-05 blank spend cap, a-07 「AI 金鑰接受任何字串」): the settings fields send what was
 * typed — a blank is null, never 0 — and print the server's sentence under the field; no local bound. */
describe("settings fields send the typed text and print the server's sentence", () => {
  afterEach(() => vi.unstubAllGlobals());

  function refuse(sentence: string) {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ error: sentence }), { status: 400 }));
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  function sentBody(fetchMock: ReturnType<typeof vi.fn>): unknown {
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    return JSON.parse(String(init.body));
  }

  it("a blank spend cap is sent as null and the server's 請填數字 shows under the field", async () => {
    const { SpendCapSection } = await vi.importActual<typeof import("./SpendCapSection")>("./SpendCapSection");
    const fetchMock = refuse("花費上限請填數字。");
    render(<SpendCapSection data={SETTINGS} onSaved={() => {}} />);
    const field = screen.getByRole("textbox", { name: "建檔精靈等 AI 生成的花費上限" });
    await userEvent.clear(field);
    await userEvent.click(screen.getByRole("button", { name: "儲存花費上限" }));
    expect(await screen.findByText("花費上限請填數字。")).toBeTruthy();
    expect(sentBody(fetchMock)).toEqual({ intake_budget: null });
    expect(field.getAttribute("aria-invalid")).toBe("true");
    await userEvent.type(field, "4");
    expect(screen.queryByText("花費上限請填數字。")).toBeNull();
  });

  it("a typed spend cap goes as typed text — the browser keeps no bound", async () => {
    const { SpendCapSection } = await vi.importActual<typeof import("./SpendCapSection")>("./SpendCapSection");
    const fetchMock = refuse("花費上限要大於 0。");
    render(<SpendCapSection data={SETTINGS} onSaved={() => {}} />);
    const field = screen.getByRole("textbox", { name: "建檔精靈等 AI 生成的花費上限" });
    await userEvent.clear(field);
    await userEvent.type(field, " -5 ");
    await userEvent.click(screen.getByRole("button", { name: "儲存花費上限" }));
    expect(await screen.findByText("花費上限要大於 0。")).toBeTruthy();
    expect(sentBody(fetchMock)).toEqual({ intake_budget: "-5" });
  });

  it("the AI monthly limit and the AI key print the server's sentences", async () => {
    const { ApiKeySection } = await vi.importActual<typeof import("./ApiKeySection")>("./ApiKeySection");
    let fetchMock = refuse("AI 月費上限請填數字。");
    render(<ApiKeySection data={SETTINGS} onSaved={() => {}} />);
    const cap = screen.getByRole("textbox", { name: "AI 月費上限（整個組織）" });
    await userEvent.clear(cap);
    await userEvent.click(screen.getByRole("button", { name: "儲存月費上限" }));
    expect(await screen.findByText("AI 月費上限請填數字。")).toBeTruthy();
    expect(sentBody(fetchMock)).toEqual({ ai_monthly_cost_limit: null });

    const keySentence = "AI 金鑰要以 sk-ant- 開頭，請從 Anthropic 主控台複製完整的一串。";
    fetchMock = refuse(keySentence);
    await userEvent.type(screen.getByPlaceholderText("貼上以 sk-ant- 開頭的金鑰"), "abc");
    await userEvent.click(screen.getByRole("button", { name: "儲存金鑰" }));
    expect(await screen.findByText(keySentence)).toBeTruthy();
    expect(sentBody(fetchMock)).toEqual({ api_key: "abc" });
  });
});


describe("successful settings saves remain acknowledged until editing", () => {
  afterEach(() => vi.unstubAllGlobals());
  it.each([
    ["SpendCapSection", "儲存花費上限", "建檔精靈等 AI 生成的花費上限"],
    ["ApiKeySection", "儲存月費上限", "AI 月費上限（整個組織）"],
  ])("%s acknowledges a successful save", async (module, label, fieldLabel) => {
    const source = module === "SpendCapSection"
      ? await vi.importActual<typeof import("./SpendCapSection")>("./SpendCapSection")
      : await vi.importActual<typeof import("./ApiKeySection")>("./ApiKeySection");
    const Component = "SpendCapSection" in source ? source.SpendCapSection : source.ApiKeySection;
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, {status:204})));
    const onSaved = vi.fn();
    render(<Component data={SETTINGS} onSaved={onSaved}/>);
    await userEvent.click(screen.getByRole("button",{name:label}));
    expect(await screen.findByText("已儲存")).toBeTruthy();
    expect(onSaved).toHaveBeenCalledTimes(1);
    const field = screen.getByRole("textbox", {name:fieldLabel});
    await userEvent.type(field,"1");
    expect(screen.queryByText("已儲存")).toBeNull();
  });
  it("model changes clear the saved acknowledgement", async () => {
    const {ModelSection}=await vi.importActual<typeof import("./ModelSection")>("./ModelSection");
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null,{status:204})));
    render(<ModelSection data={{...SETTINGS,model_choices:[{id:"model-a",name:"A",price_text:"A"},{id:"model-b",name:"B",price_text:"B"}]}} onSaved={()=>{}}/>);
    await userEvent.click(screen.getByRole("button",{name:"儲存模型設定"}));
    expect(await screen.findByText("已儲存")).toBeTruthy();
    await userEvent.selectOptions(screen.getByRole("combobox"),"model-b");
    expect(screen.queryByText("已儲存")).toBeNull();
  });
});
