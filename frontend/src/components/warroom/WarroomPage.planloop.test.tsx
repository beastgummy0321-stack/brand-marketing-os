/** B0-45 紅燈檢查（先紅後綠，尚未修）：企劃步驟「產出這期的方案」按下去之後，畫面講的話
 * 跟後端實際發生的事對不起來的前端那一半。
 *
 * 為什麼測 `WarroomPage` 而不是單獨測 `PlanStep`：這個 bug 是兩個元件的合作出的事——
 * `WarroomPage.refresh()` 第一件事是 `setState({status:"loading"})`（WarroomPage.tsx:42），
 * 整棵樹被 `讀取中…`（:73）換掉，`PlanStep` 與 `AiCostMeter` 一起卸載，`PlanStep` 那三態
 * （generating／generate-failed／ready）純 local state 當場蒸發。只測 `PlanStep` 配一個
 * 自己寫的假 parent，測到的是假 parent，不是真正的呼叫點。
 *
 * 全程假 fetch，不連任何伺服器、不打真 LLM、不碰 data/app.db。
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WarroomPage } from "./WarroomPage";

const BRAND = "brd_test";
const CYCLE = "ccy_test";

/** 還沒出過方案的檔期：`alreadyGenerated`（PlanStep.tsx:71）判定為 false 的那一種。 */
const PLANNING_CYCLE = {
  id: CYCLE,
  brand_id: BRAND,
  start_date: "2026-08-01",
  end_date: "2026-08-31",
  status: "PLANNING",
  phase: "normal",
  objective: "sales",
  funnel_stage: null,
  budget: 30000,
  duration_days: 31,
  daily_budget: 968,
  background: null,
  pacing_strategy: "continuous",
  pacing_reason: "",
  archived: false,
  daily_below_floor: false,
  plan_version: 0,
  offer: null,
};

/** 超過這個次數就當作「停不下來」，主動讓 fetch 失敗把迴圈掐斷——測試不能真的無限跑。 */
const RUNAWAY_LIMIT = 12;

/** `planStatus` 可以是單一固定回應（case 1：後端一直回 done），也可以是一串依序消化、
 * 消化完就停在最後一個的回應（case 2：先 failed 再 running，用來戳穿「無關 refresh 把
 * PlanStep 重掛載、跟著又問了一次 plan/status」這個壞行為——修好之後這串的第二個值
 * 根本不會被讀到，因為不會有第二次掛載）。 */
function installFetch(planStatus: { status: string; message?: string } | Array<{ status: string; message?: string }>) {
  const planStatusQueue = Array.isArray(planStatus) ? [...planStatus] : null;
  const counts: Record<string, number> = {};
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    // 一定要跨一個 macrotask 才回應：假 fetch 若在同一個 microtask 內就 resolve，React 會把
    // `refresh()` 的 setState(loading) 跟隨後的 setState(ready) 併成同一次 render，`讀取中…`
    // 那一格從沒 commit 過、PlanStep 也就從沒卸載——真網路一定會 commit，harness 快到失真
    // 反而把要抓的 bug 藏起來。
    await new Promise((resolve) => setTimeout(resolve, 1));
    const envelope = (data: unknown) => new Response(JSON.stringify({ data }), { status: 200, headers: { "content-type": "application/json" } });

    if (method === "GET" && url === `/api/campaigns/${BRAND}/${CYCLE}`) {
      counts.cycleDetail = (counts.cycleDetail ?? 0) + 1;
      if (counts.cycleDetail > RUNAWAY_LIMIT) throw new Error("runaway-guard");
      return envelope({ cycle: PLANNING_CYCLE, stage: "plan", readiness_notes: [] });
    }
    if (method === "GET" && url.endsWith("/plan/status")) {
      counts.planStatus = (counts.planStatus ?? 0) + 1;
      const next = planStatusQueue ? (planStatusQueue.length > 1 ? planStatusQueue.shift()! : planStatusQueue[0]) : planStatus;
      return envelope(next);
    }
    if (method === "GET" && url.endsWith("/ai-cost-meter")) {
      counts.costMeter = (counts.costMeter ?? 0) + 1;
      return envelope({ brand_id: BRAND, spent: 1.23, limit: 20, settings_url: "/settings" });
    }
    if (method === "GET" && url.endsWith("/schedule-reminder")) return envelope(null);
    if (method === "GET" && url.endsWith("/plan/options")) {
      return envelope({ options: [], cells: [], angle_locked: false, account_structure: { campaigns: [] }, dissents: [] });
    }
    if (method === "GET" && url.endsWith("/rule-cards-learned")) return envelope([]);
    if (method === "POST" && url.endsWith("/archive")) return envelope(null);
    return envelope(null);
  });
  vi.stubGlobal("fetch", fetchMock);
  return counts;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("B0-45 企劃步驟", () => {
  it("後端說 done、檔期卻還停在 PLANNING 時，畫面要停下來，不能一直重抓", async () => {
    // `plan/status` 回 done 是常態，不是異常：`_progress_state` 沒有 entry（從沒生成過，
    // 或成功結果已被上一次讀取消化掉）後端就一律回 done
    // （routes_campaigns_open_api.py:531-533）。
    const counts = installFetch({ status: "done" });

    render(
      <MemoryRouter>
        <WarroomPage brandId={BRAND} cycleId={CYCLE} />
      </MemoryRouter>,
    );

    await waitFor(() => expect(counts.cycleDetail ?? 0).toBeGreaterThan(0));
    await new Promise((resolve) => setTimeout(resolve, 300));

    expect(
      counts.cycleDetail ?? 0,
      "PlanStep 拿到 done 只呼叫 onRefresh()（PlanStep.tsx:131）、不設終局狀態，"
        + "WarroomPage.refresh() 又把整棵樹換成讀取中並重掛載 PlanStep，掛載 effect 再問一次"
        + "——問到的還是 done，於是無限重抓：花費儀表永遠停在讀取中，畫面靜靜跳回初始按鈕",
    ).toBeLessThanOrEqual(2);

    expect(await screen.findByRole("button", { name: "產出這期的方案" })).toBeDefined();
  });

  it("出方案失敗訊息不會被無關的 parent refresh() 洗掉（契約第 3 點）", async () => {
    // 第一個回應 failed，讓 PlanStep 停在「出方案失敗」卡片；第二個回應 running 只是拿來
    // 戳穿壞行為的探針——修好之後 PlanStep 不會因為無關的 refresh 被重掛載，plan/status
    // 根本不會被問第二次，這個 running 永遠不會被讀到。
    const counts = installFetch([{ status: "failed", message: "AI 掛了，請稍後再試。" }, { status: "running" }]);

    render(
      <MemoryRouter>
        <WarroomPage brandId={BRAND} cycleId={CYCLE} />
      </MemoryRouter>,
    );

    expect(await screen.findByText("AI 掛了，請稍後再試。")).toBeDefined();

    // 「封存」是跟 PlanStep 完全無關的呼叫點（WarroomPage.tsx toggleArchive() → refresh()），
    // 用它來當「不相關的 parent refresh」最貼近票面契約，不用碰 PlanStep 內部任何東西。
    fireEvent.click(screen.getByRole("button", { name: "封存" }));

    await waitFor(() => expect(counts.cycleDetail ?? 0).toBeGreaterThanOrEqual(2));
    // 讓可能發生的重掛載 effect（包含它問的 plan/status）跑完，再確認畫面。
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(screen.getByText("AI 掛了，請稍後再試。")).toBeDefined();
  });
});
