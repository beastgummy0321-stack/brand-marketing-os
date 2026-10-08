import {act, fireEvent, render, screen, within} from "@testing-library/react";
import {MemoryRouter, Routes, Route, useLocation} from "react-router-dom";
import {beforeEach, describe, expect, it, vi} from "vitest";
import * as wizard from "@/lib/adsWizardApi";
import * as settle from "@/lib/adsSettleApi";
import * as triage from "@/lib/adsTriageApi";
import {SettlePage} from "./SettlePage";
import {NextPeriodSources} from "./NextPeriodSources";
import {nextPeriodEvidence, settleEvidence, SETTLE_BRAND, SETTLE_MONTH} from "./settleEvidence.fixtures";

vi.mock("@/lib/adsWizardApi", async original => ({...await original<typeof wizard>(), getNextPeriod: vi.fn()}));
vi.mock("@/lib/adsSettleApi", async original => ({...await original<typeof settle>(), getSettle: vi.fn(), writeSettle: vi.fn()}));
vi.mock("@/lib/adsTriageApi", async original => ({...await original<typeof triage>(), getQueue: vi.fn()}));
vi.mock("@/components/layout/WorkspaceContext", () => ({useWorkspace: () => ({scope: "fixture", identity: {org: {timezone: "Asia/Taipei", today: "2026-09-23"}}})}));
const fetchSource = vi.mocked(wizard.getNextPeriod);
function Where() {const loc = useLocation(); return <output data-testid="where">{loc.pathname}{loc.search}</output>;}
function show(query = "", full = false) {
  const params = new URLSearchParams(query.replace(/^&/, ""));
  if (!params.has("step")) params.set("step", "result");
  return render(<MemoryRouter initialEntries={[`/brands/${SETTLE_BRAND}/ads/settle/${SETTLE_MONTH}?${params}`]}>
    <Where /><Routes><Route path="*" element={full ? <SettlePage brandId={SETTLE_BRAND} month={SETTLE_MONTH} /> : <NextPeriodSources brandId={SETTLE_BRAND} month={SETTLE_MONTH} />} /></Routes>
  </MemoryRouter>);
}
beforeEach(() => {
  vi.clearAllMocks(); fetchSource.mockResolvedValue(nextPeriodEvidence());
  vi.mocked(settle.getSettle).mockResolvedValue(settleEvidence());
  vi.mocked(triage.getQueue).mockResolvedValue({items: [], counts: {} as never, total_ads: 2, kinds_available: [], kinds_pending: [], settle: null});
});

describe("completed-period source navigation", () => {
  it("uses the exact shared keys and rejects incomplete/duplicate selections", () => {
    expect(wizard.readContinuationQuery(new URLSearchParams())).toEqual({status: "none"});
    for (const query of ["source_month=2026-08", "source_month=2026-13&source_campaign=a&source_revision=r",
      "source_month=2026-08&source_campaign=a&source_campaign=a&source_revision=r", "source_month=2026-08&source_campaign=&source_revision=r"]) {
      expect(wizard.readContinuationQuery(new URLSearchParams(query))).toEqual({status: "invalid"});
    }
    const selection = {month: SETTLE_MONTH, campaign_ids: ["native", "known"], revision: "r"};
    const query = wizard.withContinuationQuery(new URLSearchParams("step=note"), selection);
    expect(query.get("step")).toBe("note");
    expect(wizard.readContinuationQuery(query)).toEqual({status: "ready", selection});
  });
  it("preserves selected native identities across result/angle/back/reload without writes", async () => {
    const mounted = show("", true);
    fireEvent.click(await screen.findByRole("button", {name: "從這期來源規劃下一期"}));
    fireEvent.click(await screen.findByRole("checkbox", {name: /舊平台活動/}));
    expect(screen.getByText(/可沿用參考 0 筆/)).toBeTruthy();
    const link = screen.getByRole("link", {name: "用選定來源規劃下一期 →"});
    const query = new URLSearchParams(link.getAttribute("href")!.split("?")[1]);
    expect(wizard.readContinuationQuery(query)).toEqual({status: "ready", selection: {month: SETTLE_MONTH, campaign_ids: ["native"], revision: "source-revision-1"}});
    fireEvent.click(screen.getByRole("link", {name: "下一步：確認主打什麼 →"}));
    await screen.findByRole("heading", {name: "確認每則主打什麼"});
    expect(screen.getByTestId("where").textContent).toContain("source_campaign=native");
    fireEvent.click(screen.getByRole("link", {name: "← 這期成績"}));
    fireEvent.click(await screen.findByRole("button", {name: "從這期來源規劃下一期"}));
    expect((await screen.findByRole("checkbox", {name: /舊平台活動/}) as HTMLInputElement).checked).toBe(true);
    const stored = screen.getByTestId("where").textContent!.split("?")[1]; mounted.unmount(); show(`&${stored}`, true);
    fireEvent.click(await screen.findByRole("button", {name: "從這期來源規劃下一期"}));
    expect((await screen.findByRole("checkbox", {name: /舊平台活動/}) as HTMLInputElement).checked).toBe(true);
    expect(settle.writeSettle).not.toHaveBeenCalled();
  });
  it("retains invalid/stale selections but does not certify fresh references or create a generic link", async () => {
    show("&source_month=2026-08&source_campaign=known&source_revision=old");
    await screen.findByRole("alert");
    expect(screen.getByText(/可沿用參考 尚未核實/)).toBeTruthy();
    expect(screen.queryByRole("link", {name: "用選定來源規劃下一期 →"})).toBeNull();
    expect((screen.getByRole("checkbox", {name: /日常推廣/}) as HTMLInputElement).checked).toBe(true);
    fireEvent.click(screen.getByRole("checkbox", {name: /日常推廣/}));
    fireEvent.click(screen.getByRole("checkbox", {name: /日常推廣/}));
    expect(screen.getByText(/可沿用參考 1 筆/)).toBeTruthy();
  });
  it("keeps missing and failed sources distinct and retries without a draft write", async () => {
    fetchSource.mockRejectedValueOnce(new Error("來源讀取失敗")); show();
    await screen.findByText(/下一期來源讀不到/);
    fireEvent.click(screen.getByRole("button", {name: "重試"}));
    await screen.findByRole("checkbox", {name: /日常推廣/});
    expect(fetchSource).toHaveBeenCalledTimes(2);
    expect(settle.writeSettle).not.toHaveBeenCalled();
  });
  it("does not expose next-period sources before the period ends", async () => {
    vi.mocked(settle.getSettle).mockResolvedValue(settleEvidence("not_ended")); show("", true);
    await screen.findByText("這個月還沒結束");
    expect(screen.queryByRole("button", {name: "從這期來源規劃下一期"})).toBeNull();
    expect(fetchSource).not.toHaveBeenCalled();
  });
  it("keeps written skip rows and unknown historical counts without reclassifying retained records", async () => {
    const view = settleEvidence("written");
    view.rows[0] = {...view.rows[0], fate: "skip", grade: "insufficient", skip_reason: "目前來源讀不到"};
    vi.mocked(settle.getSettle).mockResolvedValue(view);
    show("&step=note", true);
    await screen.findByText("已寫 3 條：留存分類有效 1、無效 1、未核實 1");
    expect(screen.getByText("「通勤帶著走」・目前待核實")).toBeTruthy();
    expect(screen.getByText(/另有 1 條已寫紀錄/)).toBeTruthy();
    expect(screen.queryByText(/對這群受眾有效/)).toBeNull();
    expect(screen.queryByRole("link", {name: "＋ 建立活動"})).toBeNull();
  });
  it("preserves raw per-row purchase CPA while refusing a lead target comparison", async () => {
    const view = settleEvidence();
    view.rows[0] = {...view.rows[0], grade: "insufficient", grade_label: "資料不足", fate: "skip", reason_code: "result_kind_mismatch"};
    view.result_comparison = {reason: "mixed_result_definition"}; view.results = view.cost_per_result = view.on_target_results = null;
    vi.mocked(settle.getSettle).mockResolvedValue(view); show("", true);
    const card = await screen.findByRole("region", {name: "日常推廣・已知成本"});
    expect(within(card).getByText("每筆 50 TWD")).toBeTruthy();
    expect(within(card).getByText("成果類型與目標不同，不能比較上限")).toBeTruthy();
    const definition = within(card).getByRole("button", {name: "成果：購買・查看口徑"});
    expect(definition.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(definition);
    expect(card.textContent).toContain("成果 purchase・動作 omni_purchase・歸因 7d_click+1d_view");
    expect(within(screen.getByRole("region", {name: "這期數字"})).getAllByText("未知")).toHaveLength(2);
  });
  it("missing valid source lists cannot silently navigate to ordinary create", async () => {
    fetchSource.mockResolvedValue({...nextPeriodEvidence(), source_campaigns: [], eligible_learning_refs: []}); show();
    await screen.findByText("這個完成期沒有可選的活動來源。");
    expect(screen.queryByRole("link")).toBeNull();
  });
  it("a failed poll keeps known facts and custom picks; retry clears stale status only on success", async () => {
    const view = settleEvidence(); view.rows[0].angles = {status: "pending", candidates: []};
    vi.mocked(settle.getSettle).mockResolvedValueOnce(view).mockRejectedValueOnce(new Error("refresh unavailable")).mockResolvedValueOnce(view);
    vi.useFakeTimers();
    try {
      show("&step=angle", true); await act(async () => {await Promise.resolve();});
      fireEvent.click(screen.getAllByRole("button", {name: "＋ 自訂"})[0]);
      fireEvent.change(screen.getByRole("textbox", {name: "「通勤喝咖啡」的自訂主打"}), {target: {value: "保溫到公司"}});
      await act(async () => {vi.advanceTimersByTime(3000);});
      expect(screen.getByText(/重新讀取失敗；目前仍是上次成績/)).toBeTruthy();
      expect((screen.getByRole("textbox", {name: "「通勤喝咖啡」的自訂主打"}) as HTMLInputElement).value).toBe("保溫到公司");
      fireEvent.click(screen.getAllByRole("button", {name: "重試"})[0]); await act(async () => {await Promise.resolve();});
      expect(screen.queryByText(/重新讀取失敗；目前仍是上次成績/)).toBeNull();
      expect((screen.getByRole("textbox", {name: "「通勤喝咖啡」的自訂主打"}) as HTMLInputElement).value).toBe("保溫到公司");
    } finally {vi.useRealTimers();}
  });
  it("an older in-flight GET cannot overwrite the successful explicit notebook write", async () => {
    const view = settleEvidence(); view.rows[0].angles = {status: "pending", candidates: []};
    let resolveOld!: (view: settle.SettleView) => void;
    vi.mocked(settle.getSettle).mockResolvedValueOnce(view).mockImplementationOnce(() => new Promise(resolve => {resolveOld = resolve;}));
    vi.mocked(settle.writeSettle).mockResolvedValue(settleEvidence("written"));
    vi.useFakeTimers();
    try {
      show("&step=angle", true); await act(async () => {await Promise.resolve();});
      fireEvent.click(screen.getAllByRole("button", {name: "＋ 自訂"})[0]);
      fireEvent.change(screen.getByRole("textbox", {name: "「通勤喝咖啡」的自訂主打"}), {target: {value: "保溫到公司"}});
      await act(async () => {vi.advanceTimersByTime(3000);});
      fireEvent.click(screen.getByRole("link", {name: "都對，下一步 →"}));
      fireEvent.click(screen.getByRole("button", {name: "寫進筆記本（2 條）→"}));
      await act(async () => {await Promise.resolve();});
      await act(async () => {resolveOld(view);});
      expect(screen.getByText("已寫 3 條：留存分類有效 1、無效 1、未核實 1")).toBeTruthy();
      expect(screen.queryByRole("button", {name: "寫進筆記本（2 條）→"})).toBeNull();
    } finally {vi.useRealTimers();}
  });
  it("refresh-error retry during a pending POST cannot start another GET", async () => {
    const view = settleEvidence(); view.rows[0].angles = {status: "pending", candidates: []};
    let finishWrite!: (view: settle.SettleView) => void;
    vi.mocked(settle.getSettle).mockResolvedValueOnce(view).mockRejectedValueOnce(new Error("refresh failed"));
    vi.mocked(settle.writeSettle).mockImplementationOnce(() => new Promise(resolve => {finishWrite = resolve;}));
    vi.useFakeTimers();
    try {
      show("&step=angle", true); await act(async () => {await Promise.resolve();});
      fireEvent.click(screen.getAllByRole("button", {name: "＋ 自訂"})[0]);
      fireEvent.change(screen.getByRole("textbox", {name: "「通勤喝咖啡」的自訂主打"}), {target: {value: "保溫到公司"}});
      await act(async () => {vi.advanceTimersByTime(3000);});
      fireEvent.click(screen.getByRole("link", {name: "都對，下一步 →"}));
      fireEvent.click(screen.getByRole("button", {name: "寫進筆記本（2 條）→"}));
      fireEvent.click(screen.getByRole("button", {name: "重試"}));
      await act(async () => {await Promise.resolve();});
      expect(settle.getSettle).toHaveBeenCalledTimes(2);
      await act(async () => {finishWrite(settleEvidence("written"));});
      expect(screen.getByText("已寫 3 條：留存分類有效 1、無效 1、未核實 1")).toBeTruthy();
      expect(screen.queryByText(/重新讀取失敗/)).toBeNull();
    } finally {vi.useRealTimers();}
  });
});
