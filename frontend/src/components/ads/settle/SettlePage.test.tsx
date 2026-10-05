/** frontend/src/components/ads/settle/SettlePage.test.tsx — F29-I12: the three-step period settle. Fixtures are shaped
 * like `app/ads/settle.py::view` (Contract E, F48-I02): two campaigns (one imported from the platform, no break-even),
 * decimal costs, 划算／偏貴／太貴／沒賣出 rows, a 剛開始 row (no sale yet, ranked last-but-one as 沒賣出 rows are) and an
 * unranked row with unknown results, each with its served place in its campaign's `learning_rank` ranking; month budget
 * in the same currency. */
import type { ReactNode } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Navigate, Route, Routes, useLocation, useParams } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as settleApi from "@/lib/adsSettleApi";
import type { SettleRow, SettleView } from "@/lib/adsSettleApi";
import * as triageApi from "@/lib/adsTriageApi";
import * as jobsApi from "@/lib/jobsApi";
import type { ActiveJobsSnapshot } from "@/lib/jobsApi";
import { SettlePage, isSettleStep, settlePath } from "./SettlePage";
import { settleCsvRows } from "./settleCsv";
// F50 Contract K: the org clock reads the workspace org zone; dates assert Asia/Taipei output, never the runner's.
vi.mock("@/components/layout/WorkspaceContext", () => ({ useWorkspace: () => ({ scope: "user:org", identity: { user: { id: "u", email: "a@example.com" }, org: { id: "o", name: "測試", kind: "personal", role: "owner", timezone: "Asia/Taipei", today: "2026-10-01" }, orgs: [] } }) }));

vi.mock("@/lib/adsSettleApi", async (importOriginal) => ({
  ...(await importOriginal<typeof settleApi>()),
  getSettle: vi.fn(),
  writeSettle: vi.fn(),
}));
vi.mock("@/lib/adsTriageApi", async (importOriginal) => ({
  ...(await importOriginal<typeof triageApi>()),
  getQueue: vi.fn(),
}));
vi.mock("@/lib/jobsApi", async (importOriginal) => ({
  ...(await importOriginal<typeof jobsApi>()),
  fetchActiveJobs: vi.fn(),
}));

const getSettle = vi.mocked(settleApi.getSettle);
const writeSettle = vi.mocked(settleApi.writeSettle);
const getQueue = vi.mocked(triageApi.getQueue);
const fetchActiveJobs = vi.mocked(jobsApi.fetchActiveJobs);

const DN = "日常商品推廣・轉換";
const SN = "夏季清倉・舊帳戶（2025 年從 Meta 後台建立）";

/** `place` = [rank, of] in the campaign's ranking, `null` for a row the ranking cannot place (it is then skipped). */
function row(id: string, campaign: "a" | "b", name: string, spend: number, results: number | null, grade: SettleRow["grade"], label: string,
  place: [number, number] | null, candidates: string[] = [], reason: string | null = null): SettleRow {
  const a = campaign === "a";
  const cap = a ? 450 : 480;
  const cost = results ? spend / results : null;
  const keep = place !== null && cost !== null && cost <= cap;
  const fate: SettleRow["fate"] = place === null ? "skip" : keep ? "effective" : "ineffective";
  const few = results !== null && results >= 1 && results < 5;
  return {
    campaign_id: a ? "cmp_a" : "cmp_b", campaign_name: a ? DN : SN, origin: a ? "native" : "imported",
    entity_id: id, name, group_name: a ? "A・廣泛受眾" : "夏季・廣泛受眾", thumbnail_url: null,
    spend, results, cost_per_result: cost, cap, break_even: a ? 520 : null,
    grade, grade_label: label, reason_code: reason, currency: "TWD",
    sample: { sales: results, few, too_new: false, spend_multiple: spend / cap, days_with_events: 20 },
    rank: place?.[0] ?? null, of: place?.[1] ?? null, sales: place === null ? null : results, few: place !== null && few,
    verdict: place === null ? null : keep ? "keep" : "replace", verdict_label: place === null ? null : keep ? "留下" : "換掉", flags: few ? ["樣本少"] : [],
    fate, skip_reason: place === null ? "沒有可排名的數字" : null, copy_text: fate === "skip" ? null : `${name} 的文案。`,
    angles: fate === "skip" ? { status: "not_needed", candidates: [] } : { status: "ready", candidates }, written_angle: null,
  };
}

function view(overrides: Partial<SettleView> = {}): SettleView {
  const rows = [
    // Served order (`period_grades.grade_period`: campaign, then ad name), not rank order — printed as served.
    row("ent_1", "a", "晨光隨行杯・日常出發", 8480.5, 24, "on_target", "划算", [1, 5], ["通勤帶著走", "保溫到公司", "早晨的小儀式"]),
    row("ent_2", "a", "辦公室一角・質感桌面", 6100, 12, "watch", "偏貴", [2, 5], ["桌面質感", "辦公室好物", "上班小確幸"]),
    row("ent_3", "a", "健身情境・保冷 12 小時", 4300, 4, "over", "太貴", [3, 5], ["運動後保冷", "12 小時長效", "健身房必備"]),
    row("ent_4", "a", "秋季新色預告・直式 9:16 短影音", 1600, 0, "wasted", "沒賣出", [5, 5], ["新色搶先看", "季節限定", "顏色好看"]),
    row("ent_5", "a", "開箱 15 秒・單手開蓋", 700, 0, "insufficient", "剛開始、數字還不夠", [4, 5], ["單手就能開", "開箱實測", "隨手一按"], "too_new"),
    row("ent_6", "b", "夏日冰飲・保冷一整天", 5760, 16, "on_target", "划算", [1, 2], ["保冷一整天", "夏天消暑", "省下買飲料的錢"]),
    row("ent_7", "b", "限時 79 折・最後三天", 3900, 5, "over", "太貴", [2, 2], ["限時折扣", "最後機會", "全館優惠"]),
    row("ent_8", "b", "五種用法輪播", 900, null, "insufficient", "資料不足", null, [], "result_unknown_days"),
  ];
  const status = (label: string) => ({ state: "ready" as const, label, missing_days: [], last_success_at: "2026-09-02T00:40:00Z" });
  return {
    month: "2026-08", start: "2026-08-01", end: "2026-08-31", days: 31, status: "open", currency: "TWD",
    spent: 31740.5, budget: 33000, results: null, cost_per_result: null, on_target_results: 40, on_target_spend_share: 0.4487,
    buckets: [
      { grade: "on_target", amount: 14240.5, count: 2, ads: [] }, { grade: "watch", amount: 6100, count: 1, ads: [] },
      { grade: "over", amount: 8200, count: 2, ads: [] }, { grade: "wasted", amount: 1600, count: 1, ads: [] },
      { grade: "insufficient", amount: 1600, count: 2, ads: [] }, { grade: "no_target", amount: 0, count: 0, ads: [] },
    ],
    campaigns: [
      { campaign_id: "cmp_a", name: DN, origin: "native", cap: { value: 450, basis: "own" }, break_even: 520, data_status: status("資料已讀齊。") },
      { campaign_id: "cmp_b", name: SN, origin: "imported", cap: { value: 480, basis: "own" }, break_even: null, data_status: status("資料已讀齊。") },
    ],
    rows, notebook: { count: 14 }, written: null,
    ...overrides,
  };
}

/** The two settle routes as `App.tsx` mounts them: `/settle/:month?step=` renders the page (`key` on the month), the
 * old `/settle/:month/:step` path redirects to the query form. */
function Route_() {
  const { brandId, month } = useParams();
  return <SettlePage key={month} brandId={brandId ?? ""} month={month ?? ""} />;
}
function StepRedirect() {
  const { brandId, month, step } = useParams();
  return <Navigate to={settlePath(brandId ?? "", month ?? "", isSettleStep(step) ? step : "result")} replace />;
}

/** The same rule as `AppShell.tsx:27`: the page is re-keyed on the pathname (a query string keeps it mounted). */
function Shell({ children }: { children: ReactNode }) {
  const location = useLocation();
  return <div key={location.pathname}>{children}</div>;
}

function renderAt(step: string, url = `/brands/brd_1/ads/settle/2026-08?step=${step}`) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Shell>
        <Routes>
          <Route path="/brands/:brandId/ads/settle/:month" element={<Route_ />} />
          <Route path="/brands/:brandId/ads/settle/:month/:step" element={<StepRedirect />} />
          <Route path="/brands/:brandId/ads" element={<p>投放中心首頁</p>} />
        </Routes>
        <Where />
      </Shell>
    </MemoryRouter>,
  );
}

/** The current URL, for asserting a step change or a redirect. */
function Where() {
  const location = useLocation();
  return <output data-testid="where">{location.pathname}{location.search}</output>;
}

const jobs = (entityId: string, position: number): ActiveJobsSnapshot => ({
  data: [{ brand_id: "brd_1", brand_name: "b", kind: "ads_angles", status: "queued", stage: "", started_at: "", action_url: "", position,
    task_name: "background.ads_angles", scope: { entity_id: entityId }, waited_seconds: 20 }],
  total: 5, other_count: 3, done_today: 0, failed_today: 0, generated_at: "2026-09-02T02:20:00Z",
});

beforeEach(() => {
  vi.clearAllMocks();
  getQueue.mockResolvedValue({ items: [], counts: {} as never, total_ads: 8, kinds_available: [], kinds_pending: [], settle: null });
  fetchActiveJobs.mockResolvedValue(jobs("ent_1", 2));
});

describe("SettlePage step 1 這期成績", () => {
  it("groups rows per campaign; an imported campaign carries its origin tag and its own cap", async () => {
    getSettle.mockResolvedValue(view());
    renderAt("result");
    const imported = await screen.findByRole("region", { name: SN });
    expect(within(imported).getByText("從 Meta 帶進來")).toBeTruthy();
    expect(within(imported).getByText(/的上限 480/)).toBeTruthy();
    expect(within(imported).getByText("夏日冰飲・保冷一整天")).toBeTruthy();
    expect(within(imported).queryByText("晨光隨行杯・日常出發")).toBeNull();
    const own = screen.getByRole("region", { name: DN });
    expect(within(own).queryByText("從 Meta 帶進來")).toBeNull();
    expect(within(own).getByText("日常商品推廣的上限 450")).toBeTruthy();
    expect(screen.getByText("45%")).toBeTruthy();
    expect(screen.getByText("在這期預算 33,000 內")).toBeTruthy();
  });

  it("each row prints its served place, sales and 樣本少; the fate follows the ranking, never a sample gate", async () => {
    getSettle.mockResolvedValue(view());
    renderAt("result");
    const own = await screen.findByRole("region", { name: DN });
    const li = (name: string) => within(own).getByText(name).closest("li") as HTMLElement;
    const good = li("晨光隨行杯・日常出發");
    expect(within(good).getByText("第 1／5 名・成交 24 筆")).toBeTruthy();
    expect(within(good).getByText("記成有效")).toBeTruthy();
    expect(within(good).getByText(/每筆 353 元/)).toBeTruthy();
    expect(within(good).queryByText("樣本少")).toBeNull();
    const few = li("健身情境・保冷 12 小時");
    expect(within(few).getByText("第 3／5 名・成交 4 筆")).toBeTruthy();
    expect(within(few).getByText("樣本少")).toBeTruthy();
    expect(within(few).getByText("記成無效")).toBeTruthy();
    // 剛開始 (a known zero under the 沒賣出 line) is ranked like every unsold row; no gate sentence is printed.
    const fresh = li("開箱 15 秒・單手開蓋");
    expect(fresh.getAttribute("data-fate")).toBe("ineffective");
    expect(within(fresh).getByText("第 4／5 名・成交 0 筆")).toBeTruthy();
    expect(within(fresh).getAllByText("剛開始、數字還不夠").length).toBeGreaterThan(0);
    expect(own.textContent).not.toMatch(/要花到|跑滿|賣出 10 筆/);
    const wasted = li("秋季新色預告・直式 9:16 短影音");
    expect(within(wasted).getByText("記成無效")).toBeTruthy();
    expect(within(wasted).getByText("1,350", { exact: false })).toBeTruthy();
    // Rows stay in the served order (by name), not re-sorted by rank.
    expect([...own.querySelectorAll("li[data-rank]")].map((x) => x.getAttribute("data-rank"))).toEqual(["1", "2", "3", "5", "4"]);
  });

  it("an unranked row is not written and says why", async () => {
    getSettle.mockResolvedValue(view());
    renderAt("result");
    const imported = await screen.findByRole("region", { name: SN });
    const thin = within(imported).getByText("五種用法輪播").closest("li") as HTMLElement;
    expect(thin.getAttribute("data-fate")).toBe("skip");
    expect(within(thin).getByText("沒有可排名的數字")).toBeTruthy();
    expect(within(thin).getAllByText("資料不足").length).toBeGreaterThan(0);
    expect(within(thin).queryByText(/名・成交/)).toBeNull();
    expect(screen.getByText("排名留下的記成有效、換掉的記成無效；排不上名的不記")).toBeTruthy();
  });

  it("before the month ends, step 1 is read-only and later steps lead back to it", async () => {
    getSettle.mockResolvedValue(view({ status: "not_ended" }));
    renderAt("note");
    expect(await screen.findByRole("heading", { name: "這期成績" })).toBeTruthy();
    expect((screen.getByRole("button", { name: "下一步：確認主打什麼 →" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("這個月還沒結束，結束後才能結算")).toBeTruthy();
    expect(screen.queryByRole("link", { name: /晚點再結算/ })).toBeNull();
    expect(writeSettle).not.toHaveBeenCalled();
  });

  it("the old path step redirects to the query step; a missing or unknown step is step 1 at its canonical URL", async () => {
    getSettle.mockResolvedValue(view());
    const where = () => screen.getByTestId("where").textContent;
    const first = renderAt("angle", "/brands/brd_1/ads/settle/2026-08/angle");
    expect(where()).toBe("/brands/brd_1/ads/settle/2026-08?step=angle");
    expect(await screen.findByRole("heading", { name: "確認每則主打什麼" })).toBeTruthy();
    first.unmount();
    for (const url of ["/brands/brd_1/ads/settle/2026-08", "/brands/brd_1/ads/settle/2026-08?step=nope", "/brands/brd_1/ads/settle/2026-08/nope"]) {
      const { unmount } = renderAt("result", url);
      expect(where()).toBe("/brands/brd_1/ads/settle/2026-08?step=result");
      unmount();
    }
  });

  it("CSV lines are the numbers on screen, unknown cost as an empty cell", () => {
    const rows = settleCsvRows(view());
    expect(rows[0]).toEqual(["活動", "來源", "廣告組", "廣告", "花費", "購買", "每賣一筆", "上限", "等級", "排名", "成交", "寫進筆記本"]);
    const wasted = rows.find((r) => r[3] === "秋季新色預告・直式 9:16 短影音");
    expect(wasted).toEqual([DN, "本系統", "A・廣泛受眾", "秋季新色預告・直式 9:16 短影音", 1600, 0, null, 450, "沒賣出", "5／5", 0, "無效"]);
    expect(rows.find((r) => r[3] === "健身情境・保冷 12 小時")?.slice(9)).toEqual(["3／5", 4, "無效"]);
    expect(rows.find((r) => r[3] === "夏日冰飲・保冷一整天")?.[1]).toBe("從 Meta 帶進來");
    expect(rows.find((r) => r[3] === "五種用法輪播")?.slice(9)).toEqual([null, null, "不記"]);
  });
});

describe("SettlePage step 2 確認每則主打什麼", () => {
  it("lists only the rows that are written, first candidate preselected", async () => {
    getSettle.mockResolvedValue(view());
    renderAt("angle");
    await screen.findByRole("heading", { name: "確認每則主打什麼" });
    expect(screen.queryByText("五種用法輪播")).toBeNull();
    expect(screen.getByText("不記的 1 則不用選")).toBeTruthy();
    expect((screen.getByRole("button", { name: "✦ 通勤帶著走" })).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("link", { name: "都對，下一步 →" })).toBeTruthy();
  });

  it("while the AI works: the queue position of its job, and no way forward yet", async () => {
    const pending = view();
    pending.rows.forEach((r) => { if (r.fate !== "skip") r.angles = { status: "pending", candidates: [] }; });
    getSettle.mockResolvedValue(pending);
    renderAt("angle");
    expect(await screen.findByText(/第 2 件／共 5 件，前面還有 1 件/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "都對，下一步 →" }) as HTMLButtonElement).disabled).toBe(true);
    expect(fetchActiveJobs).toHaveBeenCalled();
  });

  it("a failed jobs read is shown as a failure, never as an empty queue, and leaves 自訂", async () => {
    const pending = view();
    pending.rows.forEach((r) => { if (r.fate !== "skip") r.angles = { status: "pending", candidates: [] }; });
    getSettle.mockResolvedValue(pending);
    fetchActiveJobs.mockRejectedValue(new Error("讀取失敗（狀態碼 500）"));
    renderAt("angle");
    expect((await screen.findByRole("alert")).textContent).toContain("讀取失敗");
    expect(screen.getAllByRole("button", { name: "＋ 自訂" })).toHaveLength(7);
  });

  it("all angles failed: 自訂 only; typing one per row enables the next step", async () => {
    const failed = view();
    failed.rows.forEach((r) => { if (r.fate !== "skip") r.angles = { status: "failed", candidates: [] }; });
    getSettle.mockResolvedValue(failed);
    renderAt("angle");
    expect((await screen.findByRole("alert")).textContent).toContain("AI 整理的主打讀不到");
    expect(screen.queryByRole("button", { name: /✦/ })).toBeNull();
    expect((screen.getByRole("button", { name: "都對，下一步 →" }) as HTMLButtonElement).disabled).toBe(true);
    for (const [i, button] of screen.getAllByRole("button", { name: "＋ 自訂" }).entries()) {
      fireEvent.click(button);
      const input = screen.getAllByRole("textbox")[i];
      fireEvent.change(input, { target: { value: `主打${i}` } });
    }
    expect(screen.getByRole("link", { name: "都對，下一步 →" })).toBeTruthy();
  });
});

describe("SettlePage step 3 寫進筆記本", () => {
  it("keeps a non-default candidate and a custom angle across the steps under the AppShell key rule (F32-I02)", async () => {
    getSettle.mockResolvedValue(view());
    writeSettle.mockRejectedValueOnce(new Error("目前無法完成，請稍後重試。"));
    renderAt("angle");
    fireEvent.click(await screen.findByRole("button", { name: "保溫到公司" }));
    const groupB = screen.getByRole("group", { name: "夏日冰飲・保冷一整天主打什麼" });
    fireEvent.click(within(groupB).getByRole("button", { name: "＋ 自訂" }));
    fireEvent.change(screen.getByRole("textbox", { name: "「夏日冰飲・保冷一整天」的自訂主打" }), { target: { value: "辦公室冰飲" } });
    fireEvent.click(screen.getByRole("link", { name: "都對，下一步 →" }));
    expect(await screen.findByRole("heading", { name: "寫進筆記本" })).toBeTruthy();
    expect(screen.getByText("「保溫到公司」對這群受眾有效")).toBeTruthy();
    expect(screen.getByText("「辦公室冰飲」對這群受眾有效")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "寫進筆記本（7 條）→" }));
    await screen.findByRole("alert");
    const sent = writeSettle.mock.calls[0][2];
    expect(sent).toContainEqual({ entity_id: "ent_1", angle: "保溫到公司" });
    expect(sent).toContainEqual({ entity_id: "ent_6", angle: "辦公室冰飲" });
  });

  it("a failed POST keeps the picks; the retry sends the same picks", async () => {
    getSettle.mockResolvedValue(view());
    writeSettle.mockRejectedValueOnce(new Error("目前無法完成，請稍後重試。"));
    renderAt("angle");
    fireEvent.click(await screen.findByRole("button", { name: "12 小時長效" }));
    fireEvent.click(screen.getByRole("link", { name: "都對，下一步 →" }));
    expect(await screen.findByText("「12 小時長效」對這群受眾無效")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "寫進筆記本（7 條）→" }));
    expect((await screen.findByRole("alert")).textContent).toContain("還沒寫進筆記本");
    expect(screen.getByText("「12 小時長效」對這群受眾無效")).toBeTruthy();
    const sent = writeSettle.mock.calls[0][2];
    expect(sent).toContainEqual({ entity_id: "ent_3", angle: "12 小時長效" });
    expect(sent).toContainEqual({ entity_id: "ent_1", angle: "通勤帶著走" });
    expect(sent).toHaveLength(7);

    const written = view({ status: "written", notebook: { count: 21 }, written: { at: "2026-09-02T02:20:00Z", by: "usr_1", count: 7, effective: 2, ineffective: 5 } });
    written.rows.forEach((r) => { if (r.fate !== "skip") r.written_angle = r.entity_id === "ent_3" ? "12 小時長效" : r.angles.candidates[0]; });
    writeSettle.mockResolvedValueOnce(written);
    fireEvent.click(screen.getByRole("button", { name: "寫進筆記本（7 條）→" }));
    expect(await screen.findByText("寫好了 7 條：有效 2、無效 5")).toBeTruthy();
    expect(writeSettle.mock.calls[1][2]).toEqual(sent);
    expect(screen.getByText("原本 14 條")).toBeTruthy();
  });

  it("reopening a written month shows what was written, without asking again", async () => {
    const written = view({ status: "written", notebook: { count: 21 }, written: { at: "2026-09-02T02:20:00Z", by: "usr_1", count: 7, effective: 2, ineffective: 5 } });
    written.rows.forEach((r) => { if (r.fate !== "skip") { r.written_angle = r.angles.candidates[0]; r.angles = { status: "not_needed", candidates: [] }; } });
    getSettle.mockResolvedValue(written);
    renderAt("angle");
    expect(await screen.findByRole("heading", { name: "寫進筆記本了" })).toBeTruthy();
    expect(screen.getByText("多了 7 條")).toBeTruthy();
    expect(screen.getByText("「通勤帶著走」對這群受眾有效")).toBeTruthy();
    expect(screen.getByText("「新色搶先看」對這群受眾無效")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /寫進筆記本（/ })).toBeNull();
    expect(screen.getByRole("link", { name: "回投放中心 →" })).toBeTruthy();
    expect(writeSettle).not.toHaveBeenCalled();
  });

  it("a failed read is its own state with a retry", async () => {
    getSettle.mockRejectedValueOnce(new Error("伺服器忙碌")).mockResolvedValueOnce(view());
    renderAt("result");
    expect((await screen.findByRole("alert")).textContent).toContain("這期成績讀不到");
    fireEvent.click(screen.getByRole("button", { name: "重試" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "這期成績" })).toBeTruthy());
  });
});

// F49 Contract Q: the settle row's place among today's decisions is served (`position`／`decisions.open`), never recounted
// from a local kind list; 「下一件」 is the next open decision on the home board in the served order.
describe("SettlePage 今天要決定的第幾件（F49 Contract Q）", () => {
  const settleRow = (position: number) => ({
    id: "itr_s", dedupe_key: "settle", category: "ads_triage_settle", severity: "rule_warning" as const, message: "",
    action_url: "/brands/brd_1/ads/settle/2026-08?step=result", visible_from: null, status: "open", created_at: "2026-09-02T00:00:00Z",
    settle: { month: "2026-08", start: "2026-08-01", end: "2026-08-31", campaign_count: 2, imported_count: 1, learnable_count: 7, buckets: [] },
    decision: true, position, done: false,
  });
  const closeout = {
    id: "itr_c", dedupe_key: "c", category: "ads_triage_closeout", severity: "rule_warning" as const, message: "「秋季檔期」已結束，待結案",
    action_url: "/brands/brd_1/ads/campaigns/cmp_fall?tab=perf&close=1", visible_from: null, status: "open", created_at: "2026-09-02T00:00:00Z",
    campaign_id: "cmp_fall", decision: true, position: 1, done: false,
    closeout: { campaign_id: "cmp_fall", campaign_name: "秋季檔期", end_date: "2026-08-31", running: { count: 0, read_at: null } },
  };

  it("prints the settle row's served position over decisions.open", async () => {
    getQueue.mockResolvedValue({ items: [], counts: {} as never, total_ads: 8, kinds_available: [], kinds_pending: [],
      settle: settleRow(2), closeouts: [closeout], decisions: { kinds: [], open: 4 } });
    getSettle.mockResolvedValue(view());
    renderAt("result");
    expect(await screen.findByText("今天要決定的第 2 件（共 4 件）")).toBeTruthy();
  });

  it("no settle row in the queue: no position is invented", async () => {
    getSettle.mockResolvedValue(view());
    renderAt("result");
    await screen.findByRole("heading", { name: "這期成績" });
    expect(screen.queryByText(/今天要決定的第/)).toBeNull();
  });

  it("written: 下一件 is the next open decision in served order (a closeout row included)", async () => {
    getQueue.mockResolvedValue({ items: [], counts: {} as never, total_ads: 8, kinds_available: [], kinds_pending: [],
      settle: { ...settleRow(2), status: "resolved", done: true }, closeouts: [closeout], decisions: { kinds: [], open: 1 } });
    const written = view({ status: "written", notebook: { count: 21 }, written: { at: "2026-09-02T02:20:00Z", by: "usr_1", count: 7, effective: 2, ineffective: 5 } });
    written.rows.forEach((r) => { if (r.fate !== "skip") { r.written_angle = r.angles.candidates[0]; r.angles = { status: "not_needed", candidates: [] }; } });
    getSettle.mockResolvedValue(written);
    renderAt("note");
    expect((await screen.findByRole("link", { name: "下一件 →" })).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_fall?tab=perf&close=1");
  });
});
