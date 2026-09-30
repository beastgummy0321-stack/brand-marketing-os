/** frontend/src/components/intake/IntakeWizard.test.tsx — the seven-step brand onboarding shell
 * (F42-I06): the step dots, step 2 skipped when the brand gave no website or photo, a completed brand
 * opening step 7, and `?step=N` re-entry. The API calls are fakes (importActual + override), no server.
 * F42-I08: the walk goes through the real steps, so every step's onboarding fetch/save has a working
 * default here (`answerEveryStep`, reset before each test); a step issue adds no mocks to this file. */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/intakeApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/intakeApi")>("@/lib/intakeApi");
  return { ...actual, fetchIntakeDraft: vi.fn() };
});
vi.mock("@/lib/intakeOnboardingApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/intakeOnboardingApi")>("@/lib/intakeOnboardingApi");
  return {
    ...actual,
    fetchOnboardingStatus: vi.fn(),
    completeOnboarding: vi.fn(),
    fetchOnboardingBasics: vi.fn(),
    saveOnboardingBasics: vi.fn(),
    fetchOnboardingScan: vi.fn(),
    startOnboardingScan: vi.fn(),
    proposeCustom: vi.fn(),
    fetchOnboardingIdentity: vi.fn(),
    saveOnboardingIdentity: vi.fn(),
    fetchOnboardingEvidence: vi.fn(),
    saveOnboardingEvidence: vi.fn(),
    fetchOnboardingMedia: vi.fn(),
    saveOnboardingMedia: vi.fn(),
    fetchOnboardingTools: vi.fn(),
  };
});
vi.mock("@/components/layout/WorkspaceContext", () => ({
  useWorkspace: () => ({
    scope: "usr_1:org_1",
    refreshBrands: vi.fn(),
    brands: [{ brand_id: "brd_x", brand_name: "山嵐手作果醬 Mountain Mist Handmade Jam Co." }],
  }),
}));

import type { IntakeDraft } from "@/lib/intakeApi";
import { fetchIntakeDraft } from "@/lib/intakeApi";
import type {
  OnboardingBasics,
  OnboardingEvidence,
  OnboardingIdentity,
  OnboardingMedia,
  OnboardingScan,
  OnboardingStatus,
  OnboardingTools,
} from "@/lib/intakeOnboardingApi";
import {
  completeOnboarding,
  fetchOnboardingBasics,
  fetchOnboardingEvidence,
  fetchOnboardingIdentity,
  fetchOnboardingMedia,
  fetchOnboardingScan,
  fetchOnboardingStatus,
  fetchOnboardingTools,
  proposeCustom,
  saveOnboardingBasics,
  saveOnboardingEvidence,
  saveOnboardingIdentity,
  saveOnboardingMedia,
  startOnboardingScan,
} from "@/lib/intakeOnboardingApi";
import { IntakeWizard } from "./IntakeWizard";

const mockStatus = vi.mocked(fetchOnboardingStatus);
const mockDraft = vi.mocked(fetchIntakeDraft);
const mockBasics = vi.mocked(fetchOnboardingBasics);

// Real-shaped answers of each step's GET (a brand whose scan read one page); each PUT answers its GET.
const BASICS: OnboardingBasics = {
  name: "山嵐手作果醬 Mountain Mist Handmade Jam Co.",
  urls: ["https://mountainmist.example/"],
  photos: [],
  market_region: "TW",
  regulatory_regime: "food_tw",
  advertising_history: "has_history",
  client_name: "",
  description: "",
};
const SCAN: OnboardingScan = {
  status: "done",
  error: null,
  found: [{ area: "品牌是誰", text: "手工小批果醬・語氣溫柔", note: "頁面 1" }],
  not_found: ["媒體報導", "銷售數據"],
  prefilled: 3,
  pages_read: 1,
  photos_read: 0,
};
const IDENTITY: OnboardingIdentity = {
  positioning: { value: "山裡的水果，小鍋慢慢熬", source: "ai", note: "頁面 1" },
  tone: { values: ["溫柔"], options: ["親切", "專業", "直接", "幽默", "溫柔", "熱血"], source: "ai", note: "頁面 1" },
  visual: { value: "木桌、自然光", source: "none", note: "", photo_urls: [] },
};
const EVIDENCE: OnboardingEvidence = {
  proof: [],
  proof_kinds: [{ key: "customer_review", label: "顧客評價" }],
  policies: [],
  policy_types: [],
  cooling_off: { applies: true, disclosure: "" },
  forbidden: [],
  regime_label: "台灣食品（食安法）",
};
const MEDIA: OnboardingMedia = { media: null };
const TOOLS: OnboardingTools = { connectors: [], conversion_goal: null, conversion_goal_options: [] };

/** Every step's fetch/save answers without a server; a test overrides only what it is about. */
function answerEveryStep() {
  mockBasics.mockResolvedValue(BASICS);
  vi.mocked(saveOnboardingBasics).mockResolvedValue(BASICS);
  vi.mocked(fetchOnboardingScan).mockResolvedValue(SCAN);
  vi.mocked(startOnboardingScan).mockResolvedValue(SCAN);
  vi.mocked(proposeCustom).mockResolvedValue({ block: "tone", kind: "option", option: { label: "像鄰居" } });
  vi.mocked(fetchOnboardingIdentity).mockResolvedValue(IDENTITY);
  vi.mocked(saveOnboardingIdentity).mockResolvedValue(IDENTITY);
  vi.mocked(fetchOnboardingEvidence).mockResolvedValue(EVIDENCE);
  vi.mocked(saveOnboardingEvidence).mockResolvedValue(EVIDENCE);
  vi.mocked(fetchOnboardingMedia).mockResolvedValue(MEDIA);
  vi.mocked(saveOnboardingMedia).mockResolvedValue({ media: "photo" });
  vi.mocked(fetchOnboardingTools).mockResolvedValue(TOOLS);
  vi.mocked(completeOnboarding).mockResolvedValue({
    step: 7, completed: true, skipped_scan: false, prefill_status: "done", prefill_error: null,
  });
}

beforeEach(() => {
  answerEveryStep();
});

afterEach(() => {
  vi.resetAllMocks();
});

function status(overrides: Partial<OnboardingStatus> = {}): OnboardingStatus {
  return { step: 3, completed: false, skipped_scan: true, prefill_status: "none", prefill_error: null, ...overrides };
}

function Where() {
  const loc = useLocation();
  return <output data-testid="where">{loc.pathname + loc.search}</output>;
}

function renderWizard(initialEntry = "/brands/brd_x/intake") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/brands/:brandId/intake" element={<><IntakeWizard brandId="brd_x" /><Where /></>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("IntakeWizard", () => {
  it("七個步驟點都在，目前這一步標成 current，麵包屑是品牌建檔 › 品牌", async () => {
    mockStatus.mockResolvedValue(status({ step: 3 }));
    mockDraft.mockResolvedValue({ scan_done: true } as unknown as IntakeDraft);

    renderWizard();

    expect(await screen.findByRole("heading", { level: 1, name: "品牌是誰" })).toBeTruthy();
    const steps = screen.getAllByRole("listitem").map((li) => li.textContent);
    // Steps before the current one carry a check mark instead of their number.
    expect(steps).toEqual(["基本", "AI 讀網站", "3品牌是誰", "4證據與政策", "5素材", "6接工具", "7完成"]);
    expect(screen.getByRole("listitem", { current: "step" }).textContent).toBe("3品牌是誰");
    expect(screen.getByRole("navigation", { name: "建檔位置" }).textContent).toBe("品牌建檔›山嵐手作果醬 Mountain Mist Handmade Jam Co.");
  });

  it("沒給網站和照片：第 2 步跳過——返回直接回基本，第 2 步的點不能點", async () => {
    mockStatus.mockResolvedValue(status({ step: 3, skipped_scan: true }));
    mockDraft.mockResolvedValue({ scan_done: true } as unknown as IntakeDraft);
    mockBasics.mockReturnValue(new Promise(() => {}));

    renderWizard();

    await screen.findByRole("heading", { level: 1, name: "品牌是誰" });
    expect(screen.queryByRole("button", { name: "回到AI 讀網站" })).toBeNull();
    expect(screen.getByRole("button", { name: "回到基本" })).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "← 基本" }));

    expect(await screen.findByRole("heading", { level: 1, name: "建立品牌" })).toBeTruthy();
  });

  it("一路按下一步走到接工具", async () => {
    mockStatus.mockResolvedValue(status({ step: 3 }));
    mockDraft.mockResolvedValue({ scan_done: true } as unknown as IntakeDraft);

    renderWizard();

    await screen.findByRole("heading", { level: 1, name: "品牌是誰" });
    await userEvent.click(screen.getByRole("button", { name: "下一步 →" }));
    expect(await screen.findByRole("heading", { level: 1, name: "品牌的證據與政策" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "← 品牌是誰" })).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "下一步 →" }));
    expect(await screen.findByRole("heading", { level: 1, name: "你交得出哪些素材" })).toBeTruthy();
  });

  it("建檔已完成、網址沒帶 step：打開第 7 步「品牌建好了」", async () => {
    mockStatus.mockResolvedValue(status({ step: 7, completed: true, skipped_scan: false }));
    mockDraft.mockResolvedValue({ scan_done: true, completed: true } as unknown as IntakeDraft);

    renderWizard();

    expect(await screen.findByRole("heading", { level: 1, name: "品牌建好了" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "先看商品頁" }).getAttribute("href")).toBe("/brands/brd_x/products");
  });

  it("建檔已完成、網址帶 ?step=3：顯示第 3 步，下一步走到 ?step=4，每個步驟點都能點", async () => {
    mockStatus.mockResolvedValue(status({ step: 7, completed: true, skipped_scan: false }));
    mockDraft.mockResolvedValue({ scan_done: true, completed: true } as unknown as IntakeDraft);

    renderWizard("/brands/brd_x/intake?step=3");

    expect(await screen.findByRole("heading", { level: 1, name: "品牌是誰" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "回到AI 讀網站" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "回到完成" })).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "下一步 →" }));

    expect(await screen.findByRole("heading", { level: 1, name: "品牌的證據與政策" })).toBeTruthy();
    expect(screen.getByTestId("where").textContent).toBe("/brands/brd_x/intake?step=4");
  });

  it("建檔已完成、?step 不是 1～7 的整數：當沒給，打開第 7 步", async () => {
    mockStatus.mockResolvedValue(status({ step: 7, completed: true }));
    mockDraft.mockRejectedValue(new Error("找不到建檔進度"));

    renderWizard("/brands/brd_x/intake?step=9");

    expect(await screen.findByRole("heading", { level: 1, name: "品牌建好了" })).toBeTruthy();
  });

  it("品牌不存在時顯示找不到，而不是一片空白", async () => {
    mockStatus.mockRejectedValue(new Error("找不到這筆資料。"));
    mockDraft.mockRejectedValue(new Error("找不到建檔進度"));

    renderWizard();

    await waitFor(() => expect(screen.getByText("找不到這個品牌")).toBeTruthy());
  });
});
