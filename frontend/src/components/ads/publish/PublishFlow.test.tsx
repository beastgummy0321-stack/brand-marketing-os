/** F30-I13: the three publish steps on real-shaped launch views (Contract G) — the list's tiles, deferred ads and
 * approval, the platform step's reports, mismatch and readback, and the verify step's hero, per-item states,
 * unreadable fields and settings readback. The F29 settings blocks have their own tests and are stubs here. */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getCampaign, getPublish, publishCampaign, type CampaignDetail } from "@/lib/adsApi";
import { reportHandoff } from "@/lib/adsHandoffApi";
import {
  confirmAllLaunchFields, confirmLaunchItemField, fetchChannels, fetchLaunchView, readbackLaunch, unreportLaunchItem,
  type LaunchItem, type LaunchMonthBudget, type LaunchView,
} from "@/lib/adsLaunchApi";
import { confirmLaunchSetting } from "@/lib/adsLaunchSettingsApi";
import { PublishPage } from "../PublishPage";

vi.mock("@/lib/adsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsApi")>("@/lib/adsApi");
  return { ...actual, getCampaign: vi.fn(), getPublish: vi.fn(), publishCampaign: vi.fn() };
});
vi.mock("@/lib/adsHandoffApi", () => ({ reportHandoff: vi.fn(), getHandoff: vi.fn() }));
vi.mock("@/lib/adsLaunchApi", () => ({
  fetchChannels: vi.fn(), fetchLaunchView: vi.fn(), readbackLaunch: vi.fn(), unreportLaunchItem: vi.fn(), confirmLaunchItemField: vi.fn(),
  confirmAllLaunchFields: vi.fn(),
}));
vi.mock("@/lib/adsLaunchSettingsApi", () => ({ confirmLaunchSetting: vi.fn() }));
vi.mock("@/lib/auth", () => ({ getOrgId: () => "org_1" }));
vi.mock("./LaunchSettingsCard", async () => {
  const { useEffect } = await vi.importActual<typeof import("react")>("react");
  return { LaunchSettingsCard: ({ locked, onBlockerChange, onCampaignSaved, campaign }: {
    locked: boolean; onBlockerChange?: (b: string | null) => void; onCampaignSaved: (c: unknown) => void; campaign: unknown;
  }) => {
    useEffect(() => { onBlockerChange?.(null); }, [onBlockerChange]);
    return <p>投放設定卡{locked ? "・唯讀" : ""}<button type="button" onClick={() => onCampaignSaved(campaign)}>存各廣告組的其他設定</button></p>;
  } };
});
vi.mock("./LaunchSettingsCopy", () => ({ LaunchSettingsCopy: () => <p>可複製的投放設定</p> }));

const LONG = "通勤情境單圖・好攜帶，走到哪都適合（最多數量 1150706）";
function item(o: Partial<LaunchItem> & Pick<LaunchItem, "id" | "kind" | "name">): LaunchItem {
  return { parent_name: null, fields: [{ key: "name", label: "名稱", value: o.name }], state: "todo", mismatches: [], unreadable: [], reason: null, reason_at: null, ...o };
}
const ITEMS: LaunchItem[] = [
  item({ id: "h1", kind: "campaign", name: "秋季新色預購", fields: [
    { key: "name", label: "名稱", value: "秋季新色預購" }, { key: "objective", label: "目標", value: "購買" },
    { key: "start_date", label: "開始日期", value: "2026-10-01" }, { key: "end_date", label: "結束日期", value: "2026-10-31" }] }),
  item({ id: "h2", kind: "group", name: "A・廣泛受眾", parent_name: "秋季新色預購", fields: [
    { key: "name", label: "名稱", value: "A・廣泛受眾" }, { key: "budget_amount", label: "每日預算", value: 1500.5 },
    { key: "manual_settings.landing_url", label: "落地頁網址", value: "https://shop.example.com/fall" }] }),
  item({ id: "h3", kind: "ad", name: LONG, parent_name: "A・廣泛受眾", fields: [
    { key: "name", label: "名稱", value: LONG }, { key: "group", label: "放在", value: "A・廣泛受眾" },
    { key: "material", label: "素材", value: "已確認版本・圖片 1 張" }] }),
];
function view(o: Partial<LaunchView> = {}): LaunchView {
  return {
    step: "list", version: null, approved_at: null,
    summary: { campaigns: 1, groups: 1, ads: 1, daily_total: 1500.5, start: "2026-10-01", end: "2026-10-31", cap: null, slots_ready: 1, slots_total: 2 },
    items: ITEMS, deferred_ads: [{ ad_id: "ad_9", name: "秋季新色預告・直式 9:16", group_name: "A・廣泛受眾" }],
    read_at: null, settings_readback: null, ...o,
  };
}
const approvedView = (states: Partial<Record<string, Partial<LaunchItem>>> = {}, o: Partial<LaunchView> = {}) =>
  view({ step: "platform", version: 1, approved_at: "2026-09-20T06:05:00Z", items: ITEMS.map((i) => ({ ...i, ...states[i.id] })), ...o });

const CAMPAIGN = {
  id: "cmp_1", name: "秋季新色預購", origin: "internal", status: "ready", capabilities: { allowed: [], unavailable: {} },
  cap: { value: null, basis: null, own_value: null, break_even: null, price: null, product_id: null, result_kind: "purchase", result_label: "購買", missing: [], revision: 0 },
  groups: [{ id: "g1", channel_key: "meta", ads: [] }], manual_handoff: null,
} as unknown as CampaignDetail;

function Where() { return <p data-testid="where">{useLocation().pathname}</p>; }
function renderAt(step: string) {
  return render(
    <MemoryRouter initialEntries={[`/brands/brd_1/ads/campaigns/cmp_1/publish/${step}`]}>
      <Routes>
        <Route path="/brands/:b/ads/campaigns/:c/publish/:step" element={<><StepRoute /><Where /></>} />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>,
  );
}
function StepRoute() {
  const step = useLocation().pathname.split("/").pop();
  return <PublishPage brandId="brd_1" campaignId="cmp_1" step={step} />;
}

afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  vi.mocked(getCampaign).mockResolvedValue(CAMPAIGN);
  vi.mocked(fetchChannels).mockResolvedValue([{ key: "meta", label: "Meta", connected: true, state_text: "已接上" }]);
  vi.mocked(getPublish).mockResolvedValue({ adapters: [], adapter: "manual", describe: { adapter: "manual", message: null, checklist: [], content_hash: "hash_1" } } as never);
});

describe("確認上架清單", () => {
  it("four tiles: counts, the formatted daily total, no cap as unknown, and the deferred ads as the 缺圖 note", async () => {
    vi.mocked(fetchLaunchView).mockResolvedValue(view());
    renderAt("list");
    const tiles = await screen.findByRole("region", { name: "上架摘要" });
    expect(within(tiles).getByText("3 項")).toBeTruthy();
    expect(within(tiles).getByText("活動 1・廣告組 1・廣告 1")).toBeTruthy();
    expect(within(tiles).getByText("1,500.5")).toBeTruthy();
    expect(within(tiles).getByText("10/01 – 10/31")).toBeTruthy();
    expect(within(tiles).getByText("沒設上限")).toBeTruthy();
    expect(within(tiles).getByText("1／2")).toBeTruthy();
    expect(within(tiles).getByText("缺圖的那 1 則先不建立，不會花到錢；補上圖後再加上去")).toBeTruthy();
    const list = screen.getByRole("region", { name: "清單" });
    expect(within(list).getByText(LONG)).toBeTruthy();
    expect(within(list).queryByRole("button", { name: /複製/ })).toBeNull(); // the list copies nothing yet
  });

  it("an unknown daily total prints 未設定, never 0", async () => {
    vi.mocked(fetchLaunchView).mockResolvedValue(view({ summary: { ...view().summary, daily_total: null } }));
    renderAt("list");
    expect(await within(await screen.findByRole("region", { name: "上架摘要" })).findByText("未設定")).toBeTruthy();
  });

  it("approves the content on screen once, then moves to 到平台完成 only after the server answered", async () => {
    vi.mocked(fetchLaunchView).mockResolvedValueOnce(view()).mockResolvedValueOnce(approvedView());
    vi.mocked(publishCampaign).mockResolvedValue({ adapter: "manual", message: null, checklist: [] });
    renderAt("list");
    const approve = await screen.findByRole("button", { name: "核准上架清單 →" });
    await waitFor(() => expect((approve as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(approve);
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/brands/brd_1/ads/campaigns/cmp_1/publish/platform"));
    expect(publishCampaign).toHaveBeenCalledWith("brd_1", "cmp_1", "manual", { content_hash: "hash_1", operation_id: expect.any(String) });
    expect(await screen.findByRole("heading", { name: "到平台完成" })).toBeTruthy();
  });

  it("a refused approval (409 launch_no_ready_ads) stays on the list with the server's words", async () => {
    vi.mocked(fetchLaunchView).mockResolvedValue(view());
    vi.mocked(publishCampaign).mockRejectedValue(new Error("還沒有任何一則廣告的素材就緒；至少一則素材確認後才能核准上架。"));
    renderAt("list");
    const approve = await screen.findByRole("button", { name: "核准上架清單 →" });
    await waitFor(() => expect((approve as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(approve);
    expect((await screen.findByRole("alert")).textContent).toContain("至少一則素材確認後才能核准上架");
    expect(screen.getByTestId("where").textContent).toBe("/brands/brd_1/ads/campaigns/cmp_1/publish/list");
  });

  it("F47-I06 (Q5): saving 各廣告組的其他設定 reads the approval content again, so approving right after does not 409", async () => {
    vi.mocked(fetchLaunchView).mockResolvedValue(view());
    renderAt("list");
    const approve = await screen.findByRole("button", { name: "核准上架清單 →" });
    await waitFor(() => expect((approve as HTMLButtonElement).disabled).toBe(false));
    const reads = vi.mocked(getPublish).mock.calls.length;
    vi.mocked(getPublish).mockResolvedValue({ adapters: [], adapter: "manual", describe: { adapter: "manual", message: null, checklist: [], content_hash: "hash_2" } } as never);
    fireEvent.click(screen.getByRole("button", { name: "存各廣告組的其他設定" }));
    await waitFor(() => expect(vi.mocked(getPublish).mock.calls.length).toBe(reads + 1));
    vi.mocked(publishCampaign).mockResolvedValue({ adapter: "manual", message: null, checklist: [] });
    await waitFor(() => expect((approve as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(approve);
    await waitFor(() => expect(publishCampaign).toHaveBeenCalledWith("brd_1", "cmp_1", "manual", { content_hash: "hash_2", operation_id: expect.any(String) }));
  });

  it("F47-I06 (Q5): a 409 because the content moved says the settings just changed and reads it again", async () => {
    vi.mocked(fetchLaunchView).mockResolvedValue(view());
    vi.mocked(publishCampaign).mockRejectedValueOnce(new Error("計畫、素材或月份已改變，請重新檢視後核准。"));
    renderAt("list");
    const approve = await screen.findByRole("button", { name: "核准上架清單 →" });
    await waitFor(() => expect((approve as HTMLButtonElement).disabled).toBe(false));
    vi.mocked(getPublish).mockResolvedValue({ adapters: [], adapter: "manual", describe: { adapter: "manual", message: null, checklist: [], content_hash: "hash_2" } } as never);
    fireEvent.click(approve);
    expect((await screen.findByRole("alert")).textContent).toBe("設定剛改過，已重新讀取，請再按一次核准");
    vi.mocked(publishCampaign).mockResolvedValue({ adapter: "manual", message: null, checklist: [] });
    await waitFor(() => expect((approve as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(approve);
    await waitFor(() => expect(publishCampaign).toHaveBeenLastCalledWith("brd_1", "cmp_1", "manual", { content_hash: "hash_2", operation_id: expect.any(String) }));
  });

  it("zero ready ads: approval waits and says why", async () => {
    vi.mocked(fetchLaunchView).mockResolvedValue(view({ summary: { ...view().summary, ads: 0, slots_ready: 0 } }));
    renderAt("list");
    expect(await screen.findByText("還沒有任何一則廣告的素材就緒，先到素材補圖")).toBeTruthy();
    expect((screen.getByRole("button", { name: "核准上架清單 →" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("after approval the list is read only and leads on to 到平台完成", async () => {
    vi.mocked(fetchLaunchView).mockResolvedValue(approvedView());
    renderAt("list");
    expect(await screen.findByText("投放設定卡・唯讀")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "核准上架清單 →" })).toBeNull();
    expect(screen.getByRole("link", { name: "到平台完成 →" }).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/publish/platform");
  });
});

/** F41-I03's list-step block, real shape: `month_budget.view(...)` of the month without this launch, this launch's
 * `extra`, and the backend's own blocker (judged with the launch) and its sentence. */
function monthBlock(o: Partial<LaunchMonthBudget> = {}): LaunchMonthBudget {
  return {
    month: "2026-10", currency: "TWD", amount: 32000, revision: 1, known_spend: 20068, ongoing_estimate: 0,
    reserved_increases: 0, available: 11932, uncertainties: [], can_increase: true, period_end: "2026-10-31",
    confirmed_at: "2026-09-30T02:00:00Z", notice: "", ongoing_owners: [], extra: 10000, blocker: null, blocker_text: null, ...o,
  };
}
const monthCard = () => screen.getByRole("region", { name: "本月預算放得下" });
async function approveButton() {
  return (await screen.findByRole("button", { name: "核准上架清單 →" })) as HTMLButtonElement;
}

describe("確認上架清單・本月預算 (F41-I05)", () => {
  it("fits: the month before this launch, this launch on top, and approval open", async () => {
    vi.mocked(fetchLaunchView).mockResolvedValue(view({ month_budget: monthBlock() }));
    renderAt("list");
    const approve = await approveButton();
    await waitFor(() => expect(approve.disabled).toBe(false));
    const card = monthCard();
    expect(within(card).getByText("放得下")).toBeTruthy();
    expect(within(card).getByText("10 月還能花 11,932")).toBeTruthy();
    expect(within(card).getByText("這期要花 10,000", { exact: false })).toBeTruthy();
    expect(within(card).getByText("還剩 1,932", { exact: false })).toBeTruthy();
    expect(screen.getByText("核准不會改動平台")).toBeTruthy();
  });

  it("unset: a link to set the month budget, and approval waits with the backend's sentence", async () => {
    vi.mocked(fetchLaunchView).mockResolvedValue(view({ month_budget: monthBlock({
      amount: null, revision: 0, available: null, confirmed_at: null, blocker: "unset", blocker_text: "要先設 10 月月預算",
    }) }));
    renderAt("list");
    expect(await screen.findByText("⚠ 要先設 10 月月預算")).toBeTruthy();
    const card = monthCard();
    expect(within(card).getByText("還沒設月預算")).toBeTruthy();
    expect(within(card).getByRole("link", { name: "設定 10 月月預算 →" }).getAttribute("href")).toBe("/brands/brd_1/ads?budget=edit");
    expect((await approveButton()).disabled).toBe(true);
  });

  it("short: 放不下, what is left against what this launch needs, the two ways out, and approval waits", async () => {
    vi.mocked(fetchLaunchView).mockResolvedValue(view({ month_budget: monthBlock({
      amount: 21000, available: 932, blocker: "short", blocker_text: "10 月預算不夠這期花",
    }) }));
    renderAt("list");
    expect(await screen.findByText("⚠ 10 月預算不夠這期花")).toBeTruthy();
    const card = monthCard();
    expect(within(card).getByText("放不下")).toBeTruthy();
    expect(within(card).queryByText("放得下")).toBeNull();
    expect(within(card).getByText("10 月只剩 932")).toBeTruthy();
    expect(within(card).getByText("不夠 9,068", { exact: false })).toBeTruthy();
    expect(within(card).getByRole("link", { name: "提高 10 月月預算" }).getAttribute("href")).toBe("/brands/brd_1/ads?budget=edit");
    expect(within(card).getByRole("link", { name: "改這期總預算" }).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1?tab=strategy");
    expect((await approveButton()).disabled).toBe(true);
  });

  it("an earlier blocker still speaks first; the month reason waits its turn", async () => {
    vi.mocked(fetchLaunchView).mockResolvedValue(view({
      summary: { ...view().summary, ads: 0, slots_ready: 0 },
      month_budget: monthBlock({ amount: null, available: null, blocker: "unset", blocker_text: "要先設 10 月月預算" }),
    }));
    renderAt("list");
    expect(await screen.findByText("還沒有任何一則廣告的素材就緒，先到素材補圖")).toBeTruthy();
    expect(screen.queryByText("⚠ 要先設 10 月月預算")).toBeNull();
  });

  it("no month block (older backend, or null): no card and no extra blocker", async () => {
    vi.mocked(fetchLaunchView).mockResolvedValue(view({ month_budget: null }));
    renderAt("list");
    const approve = await approveButton();
    await waitFor(() => expect(approve.disabled).toBe(false));
    expect(screen.queryByRole("region", { name: "本月預算放得下" })).toBeNull();
  });
});

describe("到平台完成", () => {
  it("opens the platform's ads manager in a new tab only; readback waits until something is built", async () => {
    vi.mocked(fetchLaunchView).mockResolvedValue(approvedView());
    renderAt("platform");
    const link = await screen.findByRole("link", { name: "↗ 打開 Meta 廣告管理員" });
    expect(link.getAttribute("target")).toBe("_blank");
    expect(screen.getByText("0／3 已核對")).toBeTruthy();
    expect(screen.getByText("待操作 3")).toBeTruthy();
    expect((screen.getByRole("button", { name: /讀回核對/ }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("先勾起已建好的項目")).toBeTruthy();
    expect(screen.getByRole("button", { name: "複製落地頁網址" })).toBeTruthy();
  });

  it("我建好了 reports the item and shows the refreshed state; 取消 takes the report back", async () => {
    vi.mocked(fetchLaunchView).mockResolvedValueOnce(approvedView()).mockResolvedValueOnce(approvedView({ h1: { state: "built" } }));
    vi.mocked(reportHandoff).mockResolvedValue({} as never);
    vi.mocked(unreportLaunchItem).mockResolvedValue(approvedView());
    renderAt("platform");
    fireEvent.click((await screen.findAllByRole("button", { name: "我建好了" }))[0]);
    expect(await screen.findByRole("button", { name: "我在 Meta 做完了，讀回核對（1 項） →" })).toBeTruthy();
    expect(reportHandoff).toHaveBeenCalledWith("brd_1", "cmp_1", "h1");
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    await waitFor(() => expect(unreportLaunchItem).toHaveBeenCalledWith("brd_1", "cmp_1", "h1"));
    expect(await screen.findByText("先勾起已建好的項目")).toBeTruthy();
  });

  it("a mismatch shows what the platform has; 我改好了 re-reports it for the next readback", async () => {
    const mismatch = { state: "mismatch" as const, mismatches: [{ key: "budget_amount", label: "預算金額", expected: 1500.5, observed: 3000 }] };
    vi.mocked(fetchLaunchView).mockResolvedValueOnce(approvedView({ h2: mismatch })).mockResolvedValueOnce(approvedView({ h2: { state: "built" } }));
    vi.mocked(unreportLaunchItem).mockResolvedValue(approvedView());
    vi.mocked(reportHandoff).mockResolvedValue({} as never);
    renderAt("platform");
    expect(await screen.findByText("不符：每日預算平台是 3,000")).toBeTruthy();
    expect(screen.getByText("不符 1")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "我改好了" }));
    await screen.findByRole("button", { name: "我在 Meta 做完了，讀回核對（1 項） →" });
    expect(vi.mocked(unreportLaunchItem).mock.invocationCallOrder[0]).toBeLessThan(vi.mocked(reportHandoff).mock.invocationCallOrder[0]);
  });

  it("verified items fold away; the readback moves to 讀回核對 with the server's answer", async () => {
    vi.mocked(fetchLaunchView).mockResolvedValue(approvedView({ h1: { state: "verified" }, h2: { state: "built" } }));
    vi.mocked(readbackLaunch).mockResolvedValue(approvedView({ h1: { state: "verified" }, h2: { state: "verified" } }, { step: "verify", read_at: "2026-09-23T02:52:00Z" }));
    renderAt("platform");
    const fold = await screen.findByRole("button", { name: "已核對的 1 項" });
    expect(fold.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(screen.getByRole("button", { name: "我在 Meta 做完了，讀回核對（1 項） →" }));
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/brands/brd_1/ads/campaigns/cmp_1/publish/verify"));
    expect(await screen.findByRole("heading", { name: "讀回核對" })).toBeTruthy();
  });

  it("a failed readback keeps the page and says so", async () => {
    vi.mocked(fetchLaunchView).mockResolvedValue(approvedView({ h1: { state: "built" } }));
    vi.mocked(readbackLaunch).mockRejectedValue(new Error("平台上的物件太多，這次沒有讀完，請稍後再讀回一次。"));
    renderAt("platform");
    fireEvent.click(await screen.findByRole("button", { name: /讀回核對（1 項）/ }));
    expect((await screen.findByRole("alert")).textContent).toContain("這次沒有讀完");
    expect(screen.getByTestId("where").textContent).toBe("/brands/brd_1/ads/campaigns/cmp_1/publish/platform");
  });
});

describe("讀回核對", () => {
  const read = { step: "verify" as const, read_at: "2026-09-23T02:52:00Z" };

  it("F47-I06 (R5): a stored readback reason says when it was read, beside 重新讀回", async () => {
    const at = "2026-10-28T14:59:00Z";
    const stamp = (() => { const d = new Date(at); const p = (n: number) => String(n).padStart(2, "0"); return `${p(d.getMonth() + 1)}/${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`; })();
    vi.mocked(fetchLaunchView).mockResolvedValue(approvedView({
      h1: { state: "built", reason: "平台無法讀取此資料（代碼 2）。", reason_at: at },
      h2: { state: "built", reason: "上一層還沒讀回，這一項先不比對。" },
    }, read));
    renderAt("verify");
    expect(await screen.findByText(`${stamp} 讀回時讀不到：平台無法讀取此資料（代碼 2）。`)).toBeTruthy();
    expect(screen.getByText("上一層還沒讀回，這一項先不比對。")).toBeTruthy(); // no stored time: the bare reason
    expect(screen.getByRole("button", { name: "⟳ 重新讀回" })).toBeTruthy();
  });

  it("F47-I06: the step chip names the launch with the same rule as the crumb", async () => {
    vi.mocked(fetchLaunchView).mockResolvedValue(approvedView({ h1: { state: "verified" }, h2: { state: "verified" }, h3: { state: "verified" } }, { ...read, version: 2 }));
    const first = renderAt("verify");
    expect(await screen.findByText("第 2 版上架・3 項")).toBeTruthy();
    first.unmount();
    vi.mocked(getCampaign).mockResolvedValue({ ...CAMPAIGN, context_json: { field_sources: { cap: "copied" } } } as unknown as CampaignDetail);
    vi.mocked(fetchLaunchView).mockResolvedValue(approvedView({ h1: { state: "verified" }, h2: { state: "verified" }, h3: { state: "verified" } }, read));
    renderAt("verify");
    expect(await screen.findByText("這一期上架・3 項")).toBeTruthy();
  });

  it("all items and settings match: the ok hero with the read time and 回活動總覽", async () => {
    vi.mocked(fetchLaunchView).mockResolvedValue(approvedView({ h1: { state: "verified" }, h2: { state: "verified" }, h3: { state: "verified" } }, read));
    renderAt("verify");
    expect(await screen.findByText("3 項都和核准的一樣")).toBeTruthy();
    expect(screen.getByText(/讀回於 \d\d\/\d\d \d\d:\d\d/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "回活動總覽 →" }).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1");
  });

  it("a mismatch and a differing setting: the warn hero counts both; the approved value stands beside the platform's", async () => {
    vi.mocked(fetchLaunchView).mockResolvedValue(approvedView({
      h1: { state: "verified" },
      h2: { state: "mismatch", mismatches: [{ key: "budget_amount", label: "預算金額", expected: 1500.5, observed: 3000 }] },
    }, { ...read, settings_readback: { read_at: read.read_at, fields: [
      { key: "age", label: "年齡", expected_label: "25–54 歲", observed_label: "18–65+ 歲", state: "differ", reason: null },
      { key: "pixel_id", label: "像素", expected_label: "晨光官網像素（…4821）", observed_label: null, state: "unreadable", reason: "像素的讀取權限沒開" },
    ] } }));
    vi.mocked(confirmLaunchSetting).mockResolvedValue({} as never);
    renderAt("verify");
    expect(await screen.findByText("2 項和核准的不一樣")).toBeTruthy();
    expect(screen.getByText("1,500.5")).toBeTruthy();
    expect(screen.getByText("3,000")).toBeTruthy();
    expect(screen.getByText("核准的")).toBeTruthy();
    expect(screen.getByText("Meta 目前")).toBeTruthy();
    expect(screen.getByRole("link", { name: "回平台改 →" })).toBeTruthy();
    fireEvent.click(within(screen.getByRole("region", { name: "投放設定讀回" })).getByRole("button", { name: "我看過了，一樣" }));
    await waitFor(() => expect(confirmLaunchSetting).toHaveBeenCalledWith("brd_1", "cmp_1", "pixel_id"));
    await waitFor(() => expect(fetchLaunchView).toHaveBeenCalledTimes(2));
  });

  it("an unreadable landing URL is confirmed by eye per field; built items read 待讀回, the rest 還沒建", async () => {
    const unread = { state: "unknown" as const, unreadable: [{ key: "manual_settings.landing_url", label: "落地頁網址", confirmed: false }] };
    vi.mocked(fetchLaunchView).mockResolvedValue(approvedView({ h1: { state: "verified" }, h2: unread, h3: { state: "built" } }, read));
    vi.mocked(confirmLaunchItemField).mockResolvedValue(approvedView({ h1: { state: "verified" }, h2: { state: "verified" }, h3: { state: "built" } }, read));
    renderAt("verify");
    expect(await screen.findByText("1／3 已核對")).toBeTruthy();
    expect(screen.getByText("https://shop.example.com/fall")).toBeTruthy();
    expect(screen.getByText("待讀回")).toBeTruthy();
    expect(screen.getByRole("link", { name: "繼續建剩下的 →" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "我看過了，一樣" }));
    await waitFor(() => expect(confirmLaunchItemField).toHaveBeenCalledWith("brd_1", "cmp_1", "h2", "manual_settings.landing_url"));
    expect(await screen.findByText("2／3 已核對")).toBeTruthy();
  });

  it("the done button enables only after the view reports nothing unreadable; 全部標記 gets there in one request", async () => {
    const verified = { h1: { state: "verified" as const }, h2: { state: "verified" as const }, h3: { state: "verified" as const } };
    const pixel = (state: "unreadable" | "self_confirmed") => ({ read_at: read.read_at, fields: [
      { key: "utm" as const, label: "UTM", expected_label: "utm_source=meta", observed_label: "utm_source=meta", state: "match" as const, reason: null },
      { key: "pixel_id" as const, label: "像素", expected_label: "晨光官網像素（…4821）", observed_label: null, state, reason: "像素的讀取權限沒開" },
    ] });
    vi.mocked(fetchLaunchView).mockResolvedValue(approvedView(verified, { ...read, settings_readback: pixel("unreadable") }));
    vi.mocked(confirmAllLaunchFields).mockResolvedValue(approvedView(verified, { ...read, settings_readback: pixel("self_confirmed") }));
    renderAt("verify");
    expect(await screen.findByText("1 項還沒核對")).toBeTruthy();
    expect((screen.getByRole("button", { name: "回活動總覽 →" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("全部核對完才算上架完成")).toBeTruthy();
    const bar = screen.getByRole("group", { name: "全部標記" });
    expect(bar.textContent).toContain("1 項讀不到（像素的讀取權限沒開）");
    fireEvent.click(within(bar).getByRole("button", { name: "我在 Meta 都看過了，全部標記" }));
    expect(await screen.findByText("投放設定都核對過了")).toBeTruthy();
    expect(confirmAllLaunchFields).toHaveBeenCalledTimes(1);
    expect(confirmAllLaunchFields).toHaveBeenCalledWith("brd_1", "cmp_1");
    expect(fetchLaunchView).toHaveBeenCalledTimes(1); // the answer is the view; no second read
    expect(screen.queryByRole("group", { name: "全部標記" })).toBeNull();
    expect(screen.getByText("你確認一樣")).toBeTruthy();
    expect(screen.getByRole("link", { name: "回活動總覽 →" }).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1");
  });

  it("重新讀回 reads the batch again in place", async () => {
    vi.mocked(fetchLaunchView).mockResolvedValue(approvedView({ h1: { state: "built" } }, read));
    vi.mocked(readbackLaunch).mockResolvedValue(approvedView({ h1: { state: "verified" } }, read));
    renderAt("verify");
    fireEvent.click(await screen.findByRole("button", { name: "⟳ 重新讀回" }));
    expect(await screen.findByText("1／3 已核對")).toBeTruthy();
    expect(screen.getByTestId("where").textContent).toBe("/brands/brd_1/ads/campaigns/cmp_1/publish/verify");
  });
});
