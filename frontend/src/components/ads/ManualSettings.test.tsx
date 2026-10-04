import { beforeEach, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ManualSettings } from "./ManualSettings";
import { getCampaign, type CampaignDetail } from "@/lib/adsApi";
import { saveManualSettings } from "@/lib/adsLaunchApi";

vi.mock("@/lib/adsLaunchApi", () => ({ saveManualSettings: vi.fn() }));
vi.mock("@/lib/adsApi", () => ({ getCampaign: vi.fn() }));

type Lifecycle = CampaignDetail["lifecycle"];
function campaign(value = "", lifecycle: Lifecycle = { state: "draft", label: "草稿", can_close: false }): Pick<CampaignDetail, "id" | "lifecycle" | "manual_handoff"> {
  return { id: "c1", lifecycle, manual_handoff: {
    fields: [
      { key: "audience_source", label: "受眾來源", section: "受眾", required: true },
      { key: "execution_notes", label: "執行備註", section: "技術設定", required: false },
    ],
    pending_count: value ? 0 : 1,
    groups: [{ id: "g1", name: "再行銷", status: value ? "已填設定" : "待補設定",
      values: value ? { audience_source: value } : {} as Record<string, string>, missing: value ? [] : ["受眾來源"],
      saved_at: null, saved_by: null, ads: [] }],
  } };
}

let testSequence = 0;
let testScope = "";

function renderSettings(scope = testScope, value = "") {
  return render(<ManualSettings draftScope={scope} brandId="b1" campaign={campaign(value)} onSaved={vi.fn()} />);
}

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  testScope = `test-user:test-org-${++testSequence}`;
});

it("缺漏直達會展開巢狀區塊並聚焦正確欄位；儲存失敗仍保留輸入", async () => {
  const user = userEvent.setup();
  vi.mocked(saveManualSettings).mockRejectedValueOnce(new Error("連線中斷，請重試"));
  renderSettings();

  await user.click(screen.getByRole("button", { name: "補齊再行銷設定" }));
  const input = await screen.findByRole("textbox", { name: "受眾來源 *" });
  await waitFor(() => expect(document.activeElement).toBe(input));
  await user.type(input, "網站訪客30天");
  await user.click(screen.getByRole("button", { name: "儲存這組設定" }));

  expect(await screen.findByRole("alert")).toBeTruthy();
  expect((screen.getByDisplayValue("網站訪客30天") as HTMLInputElement).value).toBe("網站訪客30天");
  expect(saveManualSettings).toHaveBeenCalledWith("b1", "c1", "g1", { audience_source: "網站訪客30天" });
});

it("缺漏直達只切一次分頁：之後可切到其他分頁並停留，再按補齊才會再跳回", async () => {
  const user = userEvent.setup();
  renderSettings();
  await user.click(screen.getByRole("button", { name: "補齊再行銷設定" }));
  const input = await screen.findByRole("textbox", { name: "受眾來源 *" });
  await waitFor(() => expect(document.activeElement).toBe(input));

  await user.click(screen.getByRole("button", { name: "技術設定" }));
  expect(await screen.findByRole("textbox", { name: "執行備註" })).toBeTruthy();
  await new Promise((resolve) => setTimeout(resolve, 20));
  expect(screen.getByRole("textbox", { name: "執行備註" })).toBeTruthy();
  expect(screen.queryByRole("textbox", { name: "受眾來源 *" })).toBeNull();

  await user.click(screen.getByRole("button", { name: "補齊再行銷設定" }));
  const again = await screen.findByRole("textbox", { name: "受眾來源 *" });
  await waitFor(() => expect(document.activeElement).toBe(again));
});

it("輸入後收起再展開不丟草稿，收起本身不儲存也不取消", async () => {
  const user = userEvent.setup();
  renderSettings();
  await user.click(screen.getByRole("button", { name: "補齊再行銷設定" }));
  await user.type(await screen.findByRole("textbox", { name: "受眾來源 *" }), "網站訪客30天");

  await user.click(screen.getByRole("button", { name: "再行銷 · 有未儲存變更" }));
  expect(screen.queryByRole("textbox", { name: "受眾來源 *" })).toBeNull();
  expect(saveManualSettings).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "再行銷 · 有未儲存變更" }));

  expect((screen.getByRole("textbox", { name: "受眾來源 *" }) as HTMLInputElement).value).toBe("網站訪客30天");
});

it("離開後同一身份與 Campaign 恢復草稿，不跨身份恢復", async () => {
  const user = userEvent.setup();
  const first = renderSettings();
  await user.click(screen.getByRole("button", { name: "補齊再行銷設定" }));
  await user.type(await screen.findByRole("textbox", { name: "受眾來源 *" }), "待回來繼續");
  first.unmount();

  const restored = renderSettings();
  await user.click(screen.getByRole("button", { name: /人工上架設定與平台對應/ }));
  await user.click(screen.getByRole("button", { name: "再行銷 · 有未儲存變更" }));
  expect(await screen.findByText(/已恢復未儲存草稿/)).toBeTruthy();
  expect((screen.getByRole("textbox", { name: "受眾來源 *" }) as HTMLInputElement).value).toBe("待回來繼續");
  restored.unmount();

  renderSettings(`${testScope}:other-identity`);
  await user.click(screen.getByRole("button", { name: "補齊再行銷設定" }));
  expect((await screen.findByRole("textbox", { name: "受眾來源 *" }) as HTMLInputElement).value).toBe("");
});

it("重新讀取伺服器資料不覆蓋 dirty 草稿，取消則改回最新已保存值並清除草稿", async () => {
  const user = userEvent.setup();
  const onSaved = vi.fn();
  const view = render(<ManualSettings draftScope={testScope} brandId="b1" campaign={campaign()} onSaved={onSaved} />);
  await user.click(screen.getByRole("button", { name: "補齊再行銷設定" }));
  await user.type(await screen.findByRole("textbox", { name: "受眾來源 *" }), "本地草稿");

  view.rerender(<ManualSettings draftScope={testScope} brandId="b1" campaign={campaign("伺服器新值")} onSaved={onSaved} />);
  expect((screen.getByRole("textbox", { name: "受眾來源 *" }) as HTMLInputElement).value).toBe("本地草稿");
  await user.click(screen.getByRole("button", { name: "取消變更" }));
  expect((screen.getByRole("textbox", { name: "受眾來源 *" }) as HTMLInputElement).value).toBe("伺服器新值");

  view.unmount();
  renderSettings(testScope, "伺服器新值");
  await user.click(screen.getByRole("button", { name: /人工上架設定與平台對應/ }));
  await user.click(screen.getByRole("button", { name: "再行銷 · 已填設定" }));
  expect(screen.queryByText("已恢復未儲存草稿。")).toBeNull();
});

it("儲存成功清除離開草稿", async () => {
  const user = userEvent.setup();
  vi.mocked(saveManualSettings).mockResolvedValueOnce(undefined);
  vi.mocked(getCampaign).mockResolvedValueOnce(campaign("已保存") as never);
  const first = renderSettings();
  await user.click(screen.getByRole("button", { name: "補齊再行銷設定" }));
  await user.type(await screen.findByRole("textbox", { name: "受眾來源 *" }), "已保存");
  await user.click(screen.getByRole("button", { name: "儲存這組設定" }));
  await waitFor(() => expect(saveManualSettings).toHaveBeenCalledTimes(1));
  first.unmount();

  renderSettings(testScope, "已保存");
  await user.click(screen.getByRole("button", { name: /人工上架設定與平台對應/ }));
  await user.click(screen.getByRole("button", { name: "再行銷 · 已填設定" }));
  expect(screen.queryByText("已恢復未儲存草稿。")).toBeNull();
});

it("groupId (F30-I08 per-group fold): only that group, in one 人工上架設定 sub-fold; 補齊 opens it and focuses the field", async () => {
  const user = userEvent.setup();
  const two = campaign();
  two.manual_handoff!.groups.push({ id: "g2", name: "新客", status: "已填設定", values: { audience_source: "x" },
    missing: [], saved_at: null, saved_by: null, ads: [] });
  render(<ManualSettings draftScope={testScope} brandId="b1" campaign={two} groupId="g1" onSaved={vi.fn()} />);

  expect(screen.queryByText(/新客/)).toBeNull();
  expect(screen.queryByRole("button", { name: /人工上架設定與平台對應/ })).toBeNull();
  const fold = screen.getByRole("button", { name: "人工上架設定 · 待補設定" });
  expect(fold.getAttribute("aria-expanded")).toBe("false");
  await user.click(screen.getByRole("button", { name: "補齊再行銷設定" }));
  const input = await screen.findByRole("textbox", { name: "受眾來源 *" });
  await waitFor(() => expect(document.activeElement).toBe(input));
  await user.type(input, "網站訪客");
  expect(screen.getByRole("button", { name: "人工上架設定 · 有未儲存變更" })).toBeTruthy();
});

it("F49 Contract L: a campaign whose served lifecycle is closed cannot edit or save its settings", async () => {
  const user = userEvent.setup();
  render(<ManualSettings draftScope={testScope} brandId="b1" onSaved={vi.fn()}
    campaign={campaign("網站訪客", { state: "closed", label: "已結案", can_close: false })} />);
  await user.click(screen.getByRole("button", { name: /人工上架設定與平台對應/ }));
  await user.click(screen.getByRole("button", { name: "再行銷 · 已填設定" }));
  expect((screen.getByRole("textbox", { name: "受眾來源 *" }) as HTMLInputElement).disabled).toBe(true);
  expect((screen.getByRole("button", { name: "儲存這組設定" }) as HTMLButtonElement).disabled).toBe(true);
});

it("F49 Contract L: an ended campaign (not yet closed) still edits its settings", async () => {
  const user = userEvent.setup();
  render(<ManualSettings draftScope={testScope} brandId="b1" onSaved={vi.fn()}
    campaign={campaign("網站訪客", { state: "ended", label: "已結束・待結案", can_close: true })} />);
  await user.click(screen.getByRole("button", { name: /人工上架設定與平台對應/ }));
  await user.click(screen.getByRole("button", { name: "再行銷 · 已填設定" }));
  expect((screen.getByRole("textbox", { name: "受眾來源 *" }) as HTMLInputElement).disabled).toBe(false);
});

it("groupId of a group without manual settings renders nothing", () => {
  const { container } = render(<ManualSettings draftScope={testScope} brandId="b1" campaign={campaign()} groupId="other" onSaved={vi.fn()} />);
  expect(container.textContent).toBe("");
});
