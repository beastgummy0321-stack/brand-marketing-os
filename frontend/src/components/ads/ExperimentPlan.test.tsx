import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import {
  confirmComparison,
  readComparison,
  saveComparisonSettings,
  type ComparisonSettings,
  type ComparisonState,
} from "@/lib/adsExperimentApi";
import { ExperimentPlan } from "./ExperimentPlan";

vi.mock("@/lib/adsExperimentApi", () => ({
  readComparison: vi.fn(),
  confirmComparison: vi.fn(),
  saveComparisonSettings: vi.fn(),
}));

const proposal = {
  fingerprint: "fp",
  hypothesis: "只改開場",
  variable: "開場",
  variants: [
    { ad_id: "a", name: "甲", value: "問句" },
    { ad_id: "b", name: "乙", value: "敘述" },
  ],
  shared: { group: "同組", audience: "同受眾", channel: "meta", daily_budget: 500, objective: "購買" },
  metric_label: "每次轉換成本",
  window: { start: "2026-09-01", end: "2026-09-07" },
  stop: "期間結束停止收樣",
  limitation: "觀察比較，不是因果證據",
};

function settings(overrides: Partial<ComparisonSettings> = {}): ComparisonSettings {
  return {
    revision: "3",
    scope: "campaign",
    defaults: {
      min_days: 7,
      min_conversions_each: 10,
      relative_difference: 0.1,
      window: { start: "2026-09-01", end: "2026-09-07" },
    },
    effective: {
      min_days: 5,
      min_conversions_each: 10,
      relative_difference: 0.2,
      window: { start: "2026-09-01", end: "2026-09-07" },
    },
    overrides: { min_days: 5, relative_difference: 0.2 },
    customized: ["min_days", "relative_difference"],
    ...overrides,
  };
}

const confirmed = { ...proposal, confirmed_at: "now", confirmed_by: "me", timing: "before_data" as const };
const state: ComparisonState = {
  proposal,
  missing: null,
  confirmed: null,
  stale: false,
  closed: false,
  simulation: false,
  settings: settings(),
  result: { verdict: "看不出", reason: "請先確認", values: [] },
};

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  vi.mocked(readComparison).mockResolvedValue(state);
});

function mount(hasSavedComparison = false, draftScope = "user:org") {
  return render(<ExperimentPlan draftScope={draftScope} brandId="brand" campaignId="c"
    hasSavedComparison={hasSavedComparison} onViewPlan={vi.fn()} />);
}

function seedRestoredDraft() {
  sessionStorage.setItem("brand-os:ads:comparison-draft:v1:user:org:brand:c", JSON.stringify({
    base: settings(),
    draft: {
      min_days: "5", min_conversions_each: "12", relative_difference: "0.2",
      windowStart: "2026-09-01", windowEnd: "2026-09-07",
    },
    resetKeys: [],
  }));
}

async function open() {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "素材比較（選用）" }));
  await screen.findByText("只改開場");
  return user;
}

async function openAdvanced() {
  const user = await open();
  await user.click(screen.getByRole("button", { name: "進階判讀設定" }));
  return user;
}

it("未使用時不請求提案；第一次展開只讀取，不會確認", async () => {
  mount();
  expect(readComparison).not.toHaveBeenCalled();

  const user = await open();
  expect(readComparison).toHaveBeenCalledWith("brand", "c");
  expect(confirmComparison).not.toHaveBeenCalled();
  const button = screen.getByRole("button", { name: "確認這份比較計畫" });
  expect((button as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText(/A 與 B 使用實際選定素材/)).toBeTruthy();

  await user.click(screen.getByRole("checkbox"));
  vi.mocked(confirmComparison).mockResolvedValue({ ...state, confirmed });
  await user.click(button);
  await waitFor(() => expect(confirmComparison).toHaveBeenCalledWith("brand", "c", "fp"));
});

it("已有確認時可在未展開前讀取並顯示簡短狀態", async () => {
  vi.mocked(readComparison).mockResolvedValue({ ...state, confirmed, result: { verdict: "觀察到差異", reason: "甲較佳", values: [] } });
  mount(true);

  expect(await screen.findByText("已確認；目前判讀：觀察到差異")).toBeTruthy();
  expect(screen.queryByText("只改開場")).toBeNull();
});

it("缺對照只在展開比較後出現，不影響外層流程", async () => {
  vi.mocked(readComparison).mockResolvedValue({ ...state, proposal: null, missing: "缺少合格對照" });
  mount();
  expect(screen.queryByText("缺少合格對照")).toBeNull();

  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "素材比較（選用）" }));
  expect(await screen.findByText("缺少合格對照")).toBeTruthy();
  expect(screen.queryByRole("checkbox")).toBeNull();
  expect(screen.getByRole("button", { name: "前往投放結構補對照" })).toBeTruthy();
});

it("單項還原只移除該 override，其他自訂與新修改仍完整提交", async () => {
  mount();
  const user = await openAdvanced();
  const minDaysRow = screen.getByText("最少觀察天數").closest("div.rounded-md") as HTMLElement;
  await user.click(within(minDaysRow).getByRole("button", { name: "恢復此項預設" }));
  const conversions = screen.getByRole("spinbutton", { name: "每則最少轉換數" });
  await user.clear(conversions);
  await user.type(conversions, "12");
  vi.mocked(saveComparisonSettings).mockResolvedValue({
    ...state,
    settings: settings({
      revision: "4",
      effective: { ...settings().effective, min_days: 7, min_conversions_each: 12 },
      overrides: { min_conversions_each: 12, relative_difference: 0.2 },
      customized: ["min_conversions_each", "relative_difference"],
    }),
  });

  await user.click(screen.getByRole("button", { name: "儲存比較設定" }));
  expect(saveComparisonSettings).toHaveBeenCalledWith("brand", "c", "3", {
    min_conversions_each: 12,
    relative_difference: 0.2,
  });
});

it("重新讀取不覆蓋 dirty 草稿，遠端 revision 改變時要求明確取消", async () => {
  mount();
  const user = await openAdvanced();
  const conversions = screen.getByRole("spinbutton", { name: "每則最少轉換數" });
  await user.clear(conversions);
  await user.type(conversions, "12");
  vi.mocked(readComparison).mockResolvedValueOnce({
    ...state,
    settings: settings({ effective: { ...settings().effective, min_conversions_each: 20 }, revision: "4" }),
  });
  await user.click(screen.getByRole("button", { name: "重新讀取比較提案" }));
  await screen.findByText(/伺服器設定已有新版本；草稿仍以原版本保留/);
  expect((screen.getByRole("spinbutton", { name: "每則最少轉換數" }) as HTMLInputElement).value).toBe("12");
  expect((screen.getByRole("button", { name: "儲存比較設定" }) as HTMLButtonElement).disabled).toBe(true);
  await user.click(screen.getByRole("button", { name: "取消設定變更" }));
  expect((screen.getByRole("spinbutton", { name: "每則最少轉換數" }) as HTMLInputElement).value).toBe("20");
  expect(screen.getByText(/版本 4/)).toBeTruthy();
});

it.each([{ revision: "3", value: 10 }, { revision: "4", value: 20 }])(
  "restored draft cancellation before the initial read adopts revision $revision/value $value and permits confirmation",
  async ({ revision, value }) => {
  seedRestoredDraft();
  let release!: (value: ComparisonState) => void;
  vi.mocked(readComparison).mockImplementationOnce(() => new Promise((resolve) => { release = resolve; }));
  mount();
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "素材比較（選用）" }));
  await user.click(screen.getByRole("button", { name: "進階判讀設定" }));
  const conversions = screen.getByRole("spinbutton", { name: "每則最少轉換數" }) as HTMLInputElement;
  expect(conversions.value).toBe("12");
  expect(screen.getByText("讀取比較提案中…")).toBeTruthy();
  const cancel = screen.getByRole("button", { name: "取消設定變更" }) as HTMLButtonElement;
  expect(cancel.disabled).toBe(false);
  await user.click(cancel);
  const afterCancel = conversions.value;
  await act(async () => release({ ...state,
    settings: settings({ revision, effective: { ...settings().effective, min_conversions_each: value } }),
  }));
  await screen.findByText("只改開場");
  await user.click(screen.getByRole("checkbox"));
  expect({
    afterCancel,
    afterRead: conversions.value,
    dirty: screen.queryByText(/請先儲存或取消進階判讀設定/) !== null,
    confirmDisabled: (screen.getByRole("button", { name: "確認這份比較計畫" }) as HTMLButtonElement).disabled,
    storedDraft: sessionStorage.getItem("brand-os:ads:comparison-draft:v1:user:org:brand:c") !== null,
  }).toEqual({ afterCancel: "10", afterRead: String(value), dirty: false, confirmDisabled: false, storedDraft: false });
  expect(screen.getByText(new RegExp(`版本 ${revision}`))).toBeTruthy();
  expect(saveComparisonSettings).not.toHaveBeenCalled();
  expect(confirmComparison).not.toHaveBeenCalled();
});

it("cancelled restored edits stay cancelled when the initial read fails, and an explicit retry adopts current settings", async () => {
  seedRestoredDraft();
  let reject!: (reason: Error) => void;
  vi.mocked(readComparison).mockImplementationOnce(() => new Promise((_, no) => { reject = no; }));
  mount();
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "素材比較（選用）" }));
  await user.click(screen.getByRole("button", { name: "進階判讀設定" }));
  await user.click(screen.getByRole("button", { name: "取消設定變更" }));
  await act(async () => reject(new Error("讀取比較暫時失敗")));
  expect((await screen.findByRole("alert")).textContent).toBe("讀取比較暫時失敗");
  expect((screen.getByRole("spinbutton", { name: "每則最少轉換數" }) as HTMLInputElement).value).toBe("10");
  expect(screen.queryByText(/有未儲存變更/)).toBeNull();
  expect(screen.queryByRole("button", { name: "確認這份比較計畫" })).toBeNull();
  expect(sessionStorage.getItem("brand-os:ads:comparison-draft:v1:user:org:brand:c")).toBeNull();
  expect(readComparison).toHaveBeenCalledTimes(1);
  vi.mocked(readComparison).mockResolvedValueOnce({ ...state,
    settings: settings({ revision: "4", effective: { ...settings().effective, min_conversions_each: 20 } }),
  });
  await user.click(screen.getByRole("button", { name: "重新讀取比較提案" }));
  await screen.findByText("只改開場");
  expect((screen.getByRole("spinbutton", { name: "每則最少轉換數" }) as HTMLInputElement).value).toBe("20");
  expect(screen.getByText(/版本 4/)).toBeTruthy();
  expect(saveComparisonSettings).not.toHaveBeenCalled();
  expect(confirmComparison).not.toHaveBeenCalled();
});

it("a comparison reply in the cancellation turn adopts the new revision instead of retaining the old edit base", async () => {
  seedRestoredDraft();
  let release!: (value: ComparisonState) => void;
  vi.mocked(readComparison).mockImplementationOnce(() => new Promise((yes) => { release = yes; }));
  mount();
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "素材比較（選用）" }));
  await user.click(screen.getByRole("button", { name: "進階判讀設定" }));
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "取消設定變更" }));
    release({ ...state, settings: settings({ revision: "4",
      effective: { ...settings().effective, min_conversions_each: 20 },
    }) });
  });
  await screen.findByText("只改開場");
  expect((screen.getByRole("spinbutton", { name: "每則最少轉換數" }) as HTMLInputElement).value).toBe("20");
  expect(screen.getByText(/版本 4/)).toBeTruthy();
  expect(screen.queryByText(/伺服器設定已有新版本/)).toBeNull();
  await user.click(screen.getByRole("checkbox"));
  expect((screen.getByRole("button", { name: "確認這份比較計畫" }) as HTMLButtonElement).disabled).toBe(false);
  expect(saveComparisonSettings).not.toHaveBeenCalled();
  expect(confirmComparison).not.toHaveBeenCalled();
});

it("dirty 時不能確認舊設定，儲存失敗仍保留輸入", async () => {
  mount();
  const user = await openAdvanced();
  const conversions = screen.getByRole("spinbutton", { name: "每則最少轉換數" });
  await user.clear(conversions);
  await user.type(conversions, "12");
  await user.click(screen.getByRole("checkbox"));
  expect((screen.getByRole("button", { name: "確認這份比較計畫" }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText(/請先儲存或取消進階判讀設定/)).toBeTruthy();

  vi.mocked(saveComparisonSettings).mockRejectedValueOnce(new Error("版本衝突，請重新讀取"));
  await user.click(screen.getByRole("button", { name: "儲存比較設定" }));
  expect((await screen.findByRole("alert")).textContent).toContain("版本衝突");
  expect((screen.getByRole("spinbutton", { name: "每則最少轉換數" }) as HTMLInputElement).value).toBe("12");
});

it("提案不可用時仍可單獨還原過期的自訂觀察期間", async () => {
  const customWindow = { start: "2026-08-01", end: "2026-08-07" };
  vi.mocked(readComparison).mockResolvedValue({
    ...state,
    proposal: null,
    missing: "已保存的比較設定不再符合共同投放期間",
    stale: true,
    settings: settings({
      effective: { ...settings().effective, window: customWindow },
      overrides: { min_days: 5, relative_difference: 0.2, window: customWindow },
      customized: ["min_days", "relative_difference", "window"],
    }),
  });
  const user = userEvent.setup();
  mount();
  await user.click(screen.getByRole("button", { name: "素材比較（選用）" }));
  await screen.findByText(/已保存的比較設定不再符合/);
  await user.click(screen.getByRole("button", { name: "進階判讀設定" }));
  const windowRow = screen.getByText("觀察期間").closest("div.rounded-md") as HTMLElement;
  await user.click(within(windowRow).getByRole("button", { name: "恢復此項預設" }));
  vi.mocked(saveComparisonSettings).mockResolvedValue(state);

  await user.click(screen.getByRole("button", { name: "儲存比較設定" }));
  expect(saveComparisonSettings).toHaveBeenCalledWith("brand", "c", "3", {
    min_days: 5,
    relative_difference: 0.2,
  });
});

it("已結案時輸入與單項還原都停用", async () => {
  vi.mocked(readComparison).mockResolvedValue({ ...state, closed: true });
  mount();
  await openAdvanced();
  expect((screen.getByRole("spinbutton", { name: "最少觀察天數" }) as HTMLInputElement).disabled).toBe(true);
  const minDaysRow = screen.getByText("最少觀察天數").closest("div.rounded-md") as HTMLElement;
  expect((within(minDaysRow).getByRole("button", { name: "恢復此項預設" }) as HTMLButtonElement).disabled).toBe(true);
});

it("草稿跨卸載恢復，但不會跨 user/org scope", async () => {
  const view = mount();
  const user = await openAdvanced();
  const conversions = screen.getByRole("spinbutton", { name: "每則最少轉換數" });
  await user.clear(conversions);
  await user.type(conversions, "12");
  await waitFor(() => expect(sessionStorage.length).toBe(1));
  view.unmount();

  const restored = mount();
  expect(await screen.findByText(/已恢復未儲存的比較設定草稿/)).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: "素材比較（選用）" }));
  await userEvent.click(screen.getByRole("button", { name: "進階判讀設定" }));
  expect((screen.getByRole("spinbutton", { name: "每則最少轉換數" }) as HTMLInputElement).value).toBe("12");
  restored.unmount();

  mount(false, "other-user:org");
  expect(readComparison).toHaveBeenCalledTimes(2);
  expect(screen.queryByText(/已恢復未儲存的比較設定草稿/)).toBeNull();
});

it("過期確認會保留完整紀錄並標示事後觀察", async () => {
  vi.mocked(readComparison).mockResolvedValue({ ...state, stale: true, confirmed: { ...confirmed, timing: "retrospective" } });
  await openWithSaved();
  expect(screen.getAllByText(/原確認已過期/).length).toBeGreaterThan(0);
  await userEvent.click(screen.getByText("公式、識別碼與完整確認紀錄（已過期）"));
  expect(screen.getByText(/事後觀察，不是事前實驗/)).toBeTruthy();
});

async function openWithSaved() {
  mount(true);
  await screen.findByText(/原確認已過期/);
  await userEvent.click(screen.getByRole("button", { name: "素材比較（選用）" }));
  await screen.findAllByText("只改開場");
}
