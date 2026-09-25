/** frontend/src/components/ads/settle/SettlePage.test.tsx — F29-I12: the three-step period settle. Fixtures are shaped
 * like `app/ads/settle.py::view` (Contract E): two campaigns (one imported from the platform, no break-even), decimal
 * costs, 划算／偏貴／太貴／沒賣出 rows and two thin rows below the sample gate, month budget in the same currency. */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useParams } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as settleApi from "@/lib/adsSettleApi";
import type { SettleRow, SettleView } from "@/lib/adsSettleApi";
import * as triageApi from "@/lib/adsTriageApi";
import * as jobsApi from "@/lib/jobsApi";
import type { ActiveJobsSnapshot } from "@/lib/jobsApi";
import { SettlePage, isSettleStep } from "./SettlePage";
import { settleCsvRows } from "./settleCsv";

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

function row(id: string, campaign: "a" | "b", name: string, spend: number, results: number, grade: SettleRow["grade"], label: string,
  fate: SettleRow["fate"], candidates: string[] = []): SettleRow {
  const a = campaign === "a";
  return {
    campaign_id: a ? "cmp_a" : "cmp_b", campaign_name: a ? DN : SN, origin: a ? "native" : "imported",
    entity_id: id, name, group_name: a ? "A・廣泛受眾" : "夏季・廣泛受眾", thumbnail_url: null,
    spend, results, cost_per_result: results ? spend / results : null, cap: a ? 450 : 480, break_even: a ? 520 : null,
    grade, grade_label: label, currency: "TWD", fate, skip_reason: null, copy_text: fate === "skip" ? null : `${name} 的文案。`,
    angles: fate === "skip" ? { status: "not_needed", candidates: [] } : { status: "ready", candidates }, written_angle: null,
  };
}

function view(overrides: Partial<SettleView> = {}): SettleView {
  const rows = [
    row("ent_1", "a", "晨光隨行杯・日常出發", 8480.5, 24, "on_target", "划算", "effective", ["通勤帶著走", "保溫到公司", "早晨的小儀式"]),
    row("ent_2", "a", "辦公室一角・質感桌面", 6100, 12, "watch", "偏貴", "skip"),
    row("ent_3", "a", "健身情境・保冷 12 小時", 4300, 7, "over", "太貴", "ineffective", ["運動後保冷", "12 小時長效", "健身房必備"]),
    row("ent_4", "a", "秋季新色預告・直式 9:16 短影音", 1600, 0, "wasted", "沒賣出", "ineffective", ["新色搶先看", "季節限定", "顏色好看"]),
    row("ent_5", "a", "開箱 15 秒・單手開蓋", 700, 1, "insufficient", "剛開始、數字還不夠", "skip"),
    row("ent_6", "b", "夏日冰飲・保冷一整天", 5760, 16, "on_target", "划算", "effective", ["保冷一整天", "夏天消暑", "省下買飲料的錢"]),
    row("ent_7", "b", "限時 79 折・最後三天", 3900, 5, "over", "太貴", "ineffective", ["限時折扣", "最後機會", "全館優惠"]),
    row("ent_8", "b", "五種用法輪播", 900, 0, "insufficient", "剛開始、數字還不夠", "skip"),
  ];
  const status = (label: string) => ({ state: "ready" as const, label, missing_days: [], last_success_at: "2026-09-02T00:40:00Z" });
  return {
    month: "2026-08", start: "2026-08-01", end: "2026-08-31", days: 31, status: "open", currency: "TWD",
    spent: 31740.5, budget: 33000, results: 65, cost_per_result: 31740.5 / 65, on_target_results: 40, on_target_spend_share: 0.4487,
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

function Route_() {
  const { brandId, month, step } = useParams();
  return isSettleStep(step) ? <SettlePage brandId={brandId ?? ""} month={month ?? ""} step={step} /> : null;
}

function renderAt(step: string) {
  return render(
    <MemoryRouter initialEntries={[`/brands/brd_1/ads/settle/2026-08/${step}`]}>
      <Routes>
        <Route path="/brands/:brandId/ads/settle/:month/:step" element={<Route_ />} />
        <Route path="/brands/:brandId/ads" element={<p>投放中心首頁</p>} />
      </Routes>
    </MemoryRouter>,
  );
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

  it("a thin row is not written and says why; graded rows show their fate", async () => {
    getSettle.mockResolvedValue(view());
    renderAt("result");
    const own = await screen.findByRole("region", { name: DN });
    const thin = within(own).getByText("開箱 15 秒・單手開蓋").closest("li") as HTMLElement;
    expect((thin).getAttribute("data-fate")).toBe("skip");
    expect(within(thin).getByText("不記")).toBeTruthy();
    expect(within(thin).getByText(/這期不記/)).toBeTruthy();
    expect(within(thin).getByText(/要花到 1,350 元，或跑滿 7 天賣出 10 筆/)).toBeTruthy();
    const wasted = within(own).getByText("秋季新色預告・直式 9:16 短影音").closest("li") as HTMLElement;
    expect(within(wasted).getByText("記成無效")).toBeTruthy();
    const good = within(own).getByText("晨光隨行杯・日常出發").closest("li") as HTMLElement;
    expect(within(good).getByText("記成有效")).toBeTruthy();
    expect(within(good).getByText(/每筆 353 元/)).toBeTruthy();
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

  it("CSV lines are the numbers on screen, unknown cost as an empty cell", () => {
    const rows = settleCsvRows(view());
    expect(rows[0]).toEqual(["活動", "來源", "廣告組", "廣告", "花費", "購買", "每賣一筆", "上限", "等級", "寫進筆記本"]);
    const wasted = rows.find((r) => r[3] === "秋季新色預告・直式 9:16 短影音");
    expect(wasted).toEqual([DN, "本系統", "A・廣泛受眾", "秋季新色預告・直式 9:16 短影音", 1600, 0, null, 450, "沒賣出", "無效"]);
    expect(rows.find((r) => r[3] === "夏日冰飲・保冷一整天")?.[1]).toBe("從 Meta 帶進來");
    expect(rows.find((r) => r[3] === "五種用法輪播")?.[9]).toBe("不記");
  });
});

describe("SettlePage step 2 確認每則主打什麼", () => {
  it("lists only the rows that are written, first candidate preselected", async () => {
    getSettle.mockResolvedValue(view());
    renderAt("angle");
    await screen.findByRole("heading", { name: "確認每則主打什麼" });
    expect(screen.queryByText("辦公室一角・質感桌面")).toBeNull();
    expect(screen.getByText("偏貴和數字還不夠的 3 則不用選")).toBeTruthy();
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
    expect(screen.getAllByRole("button", { name: "＋ 自訂" })).toHaveLength(5);
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
  it("a failed POST keeps the picks; the retry sends the same picks", async () => {
    getSettle.mockResolvedValue(view());
    writeSettle.mockRejectedValueOnce(new Error("目前無法完成，請稍後重試。"));
    renderAt("angle");
    fireEvent.click(await screen.findByRole("button", { name: "12 小時長效" }));
    fireEvent.click(screen.getByRole("link", { name: "都對，下一步 →" }));
    expect(await screen.findByText("「12 小時長效」對這群受眾無效")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "寫進筆記本（5 條）→" }));
    expect((await screen.findByRole("alert")).textContent).toContain("還沒寫進筆記本");
    expect(screen.getByText("「12 小時長效」對這群受眾無效")).toBeTruthy();
    const sent = writeSettle.mock.calls[0][2];
    expect(sent).toContainEqual({ entity_id: "ent_3", angle: "12 小時長效" });
    expect(sent).toContainEqual({ entity_id: "ent_1", angle: "通勤帶著走" });
    expect(sent).toHaveLength(5);

    const written = view({ status: "written", notebook: { count: 19 }, written: { at: "2026-09-02T02:20:00Z", by: "usr_1", count: 5, effective: 2, ineffective: 3 } });
    written.rows.forEach((r) => { if (r.fate !== "skip") r.written_angle = r.entity_id === "ent_3" ? "12 小時長效" : r.angles.candidates[0]; });
    writeSettle.mockResolvedValueOnce(written);
    fireEvent.click(screen.getByRole("button", { name: "寫進筆記本（5 條）→" }));
    expect(await screen.findByText("寫好了 5 條：有效 2、無效 3")).toBeTruthy();
    expect(writeSettle.mock.calls[1][2]).toEqual(sent);
    expect(screen.getByText("原本 14 條")).toBeTruthy();
  });

  it("reopening a written month shows what was written, without asking again", async () => {
    const written = view({ status: "written", notebook: { count: 19 }, written: { at: "2026-09-02T02:20:00Z", by: "usr_1", count: 5, effective: 2, ineffective: 3 } });
    written.rows.forEach((r) => { if (r.fate !== "skip") { r.written_angle = r.angles.candidates[0]; r.angles = { status: "not_needed", candidates: [] }; } });
    getSettle.mockResolvedValue(written);
    renderAt("angle");
    expect(await screen.findByRole("heading", { name: "寫進筆記本了" })).toBeTruthy();
    expect(screen.getByText("多了 5 條")).toBeTruthy();
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
