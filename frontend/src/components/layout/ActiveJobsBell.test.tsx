import { MemoryRouter, useLocation } from "react-router-dom";
/** frontend/src/components/layout/ActiveJobsBell.test.tsx — F29-I05 (feature Contract G; prototype
 * v10 `topRight()`/`renderJobs()`, demos `jobs:ok` and `jobs:fail`): the top-bar pill says what
 * runs now and how many wait, the panel lists each job with its place in the whole queue and
 * today's done/failed line, and a failed read is its own state with 重試 — never 「沒有…」. */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ActiveJobsBell } from "./ActiveJobsBell";
import { fetchActiveJobs, type ActiveJob, type ActiveJobsSnapshot } from "@/lib/jobsApi";

// F50-I14: the org is in Taipei whatever zone the test runner is in.
vi.mock("./WorkspaceContext", () => ({
  useWorkspace: () => ({ identity: { org: { id: "org_1", timezone: "Asia/Taipei", today: "2026-10-03" } } }),
}));

vi.mock("@/lib/jobsApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/jobsApi")>();
  return { ...actual, fetchActiveJobs: vi.fn() };
});

function job(overrides: Partial<ActiveJob>): ActiveJob {
  return {
    brand_id: "brd_bughunt",
    brand_name: "晨光隨行杯",
    kind: "ads_sync",
    status: "queued",
    stage: "讀取廣告平台成效中",
    started_at: "",
    action_url: "/brands/brd_bughunt/ads/connections",
    position: 1,
    task_name: "background.ads_external_sync",
    scope: {},
    waited_seconds: 20,
    ...overrides,
  };
}

// Realistic shape: one of ours running, one other tenant's job in between, three of ours waiting.
const QUEUE: ActiveJobsSnapshot = {
  data: [
    job({ status: "running", position: 1, waited_seconds: 70, started_at: "2026-09-23T02:39:00Z" }),
    job({ kind: "ads_angles", task_name: "background.ads_angles", position: 3, scope: { campaign_id: "cmp_daily", entity_id: "ent_1" }, action_url: "/brands/brd_bughunt/ads/campaigns/cmp_daily/detail" }),
    job({ kind: "workbench_generate", task_name: "background.workbench_generate", position: 4, action_url: "/brands/brd_bughunt/workbench" }),
    job({ kind: "ads_review", task_name: "background.ads_review_round", position: 5, waited_seconds: 5 }),
  ],
  total: 5,
  other_count: 1,
  done_today: 12,
  failed_today: 0,
  generated_at: "2026-09-23T02:40:00Z",
  worker_alive: true,
};

beforeEach(() => {
  vi.mocked(fetchActiveJobs).mockReset();
});

describe("ActiveJobsBell", () => {
  it("unknown heartbeat overrides a legacy healthy flag and never gives an all-clear", async () => {
    vi.mocked(fetchActiveJobs).mockResolvedValue({ ...QUEUE, data: [], total: 0, worker_health: {
      state: "unknown", checked_at: QUEUE.generated_at, last_heartbeat_at: null, reason_code: "test_queue",
    } });
    render(<MemoryRouter><ActiveJobsBell /></MemoryRouter>);
    await userEvent.click(await screen.findByRole("button", { name: /背景程式狀態無法確認/ }));
    expect(screen.getByRole("alert").textContent).toContain("還不能確認工作是否繼續");
    expect(screen.getByRole("alert").textContent).not.toContain("停了");
  });

  it("pill: what runs now and how many of yours wait", async () => {
    vi.mocked(fetchActiveJobs).mockResolvedValue(QUEUE);
    render(<MemoryRouter><ActiveJobsBell /></MemoryRouter>);
    const pill = await screen.findByRole("button", { name: /正在同步成效・還有 3 件排隊/ });
    expect(pill.getAttribute("aria-expanded")).toBe("false");
  });

  it("panel: position over the whole queue, 前面還有 N 件, today's line; Escape returns focus to the pill", async () => {
    vi.mocked(fetchActiveJobs).mockResolvedValue(QUEUE);
    render(<MemoryRouter><ActiveJobsBell /></MemoryRouter>);
    const pill = await screen.findByRole("button", { name: /正在同步成效/ });
    await userEvent.click(pill);

    const panel = screen.getByRole("dialog", { name: "背景工作" });
    expect(panel.textContent).toContain("排隊 5 件");
    expect(panel.textContent).toContain("其中 1 件是系統或其他帳號的工作");
    const rows = within(panel).getAllByRole("listitem");
    expect(rows).toHaveLength(4);
    expect(rows[0].textContent).toContain("同步成效・晨光隨行杯");
    expect(rows[0].textContent).toContain("進行中・約 1 分");
    // Position 3 has the other tenant's job and ours ahead of it.
    expect(rows[1].textContent).toContain("3");
    expect(rows[1].textContent).toContain("前面還有 2 件");
    expect(rows[3].textContent).toContain("前面還有 4 件");
    expect(within(rows[1]).getByRole("link").getAttribute("href")).toBe("/brands/brd_bughunt/ads/campaigns/cmp_daily/detail");
    expect(panel.textContent).toContain("今天做完 12 件・失敗 0 件");
    expect(document.activeElement?.textContent).toBe("關閉");

    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(pill);
  });

  it("讀取於 prints 08:30 for 00:30Z with the org in Taipei, whatever the runner's zone (F50-I14, Contract K)", async () => {
    vi.mocked(fetchActiveJobs).mockResolvedValue({ ...QUEUE, generated_at: "2026-10-03T00:30:00Z" });
    render(<MemoryRouter><ActiveJobsBell /></MemoryRouter>);
    await userEvent.click(await screen.findByRole("button", { name: /正在同步成效/ }));
    expect(screen.getByRole("dialog", { name: "背景工作" }).textContent).toContain("讀取於 10/03 08:30");
  });

  it("nothing of yours queued behind the running one: no 「還有 0 件」", async () => {
    vi.mocked(fetchActiveJobs).mockResolvedValue({ ...QUEUE, data: [QUEUE.data[0]], total: 1, other_count: 0 });
    render(<MemoryRouter><ActiveJobsBell /></MemoryRouter>);
    expect(await screen.findByRole("button", { name: /^正在同步成效 ›$|正在同步成效$/ })).toBeTruthy();
  });

  it("only queued: says where the first one stands", async () => {
    vi.mocked(fetchActiveJobs).mockResolvedValue({ ...QUEUE, data: [QUEUE.data[1]], total: 3, other_count: 2 });
    render(<MemoryRouter><ActiveJobsBell /></MemoryRouter>);
    expect(await screen.findByRole("button", { name: /整理廣告主打排隊中・前面還有 2 件/ })).toBeTruthy();
  });

  it("empty but read fine: says nothing runs, still shows today's line", async () => {
    vi.mocked(fetchActiveJobs).mockResolvedValue({ ...QUEUE, data: [], total: 0, other_count: 0, done_today: 3, failed_today: 1 });
    render(<MemoryRouter><ActiveJobsBell /></MemoryRouter>);
    await userEvent.click(await screen.findByRole("button", { name: /沒有背景工作在跑/ }));
    const panel = screen.getByRole("dialog", { name: "背景工作" });
    expect(panel.textContent).toContain("目前沒有你的背景工作在跑");
    expect(panel.textContent).toContain("今天做完 3 件・失敗 1 件");
  });

  it("failed read: its own state with 重試, never an empty list; retry reads again", async () => {
    vi.mocked(fetchActiveJobs).mockRejectedValueOnce(new Error("讀取失敗（狀態碼 500）")).mockResolvedValue(QUEUE);
    render(<MemoryRouter><ActiveJobsBell /></MemoryRouter>);
    const pill = await screen.findByRole("button", { name: /背景工作讀取失敗・點開重試/ });
    await userEvent.click(pill);

    const panel = screen.getByRole("dialog", { name: "背景工作" });
    expect(within(panel).getByRole("alert").textContent).toContain("排隊狀態讀不到，還不能確認背景工作是否繼續；已填的資料保留");
    expect(panel.textContent).not.toMatch(/沒有.*背景工作|排隊 0 件/);

    await userEvent.click(within(panel).getByRole("button", { name: "重試" }));
    await waitFor(() => expect(fetchActiveJobs).toHaveBeenCalledTimes(2));
    expect(await within(panel).findByText(/排隊 5 件/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /正在同步成效/ })).toBeTruthy();
  });

  it("worker stopped: the pill says 背景程式停了 instead of 「前面還有 0 件」, the panel carries the notice; 再檢查一次 with a live worker clears it", async () => {
    // Drill 10 W2: one copy job of ours first in line, no worker heartbeat.
    const stalled: ActiveJobsSnapshot = {
      ...QUEUE, data: [job({ kind: "workbench_generate", task_name: "background.workbench_generate", position: 1 })],
      total: 1, other_count: 0, worker_alive: false, stalled: true,
    };
    vi.mocked(fetchActiveJobs).mockResolvedValue(stalled);
    render(<MemoryRouter><ActiveJobsBell /></MemoryRouter>);
    const pill = await screen.findByRole("button", { name: /背景程式停了・工作還排著/ });
    expect(pill.textContent).not.toContain("前面還有");
    await userEvent.click(pill);

    const panel = screen.getByRole("dialog", { name: "背景工作" });
    const notice = within(panel).getByText(/背景程式停了/).closest("[data-slot=worker-stopped]") as HTMLElement;
    expect(notice.textContent).toContain("背景程式停了：這件工作還排著，已填的資料沒丟。重新啟動行銷系統後會自動接著做。");
    expect(within(panel).getAllByRole("listitem")).toHaveLength(1);

    vi.mocked(fetchActiveJobs).mockResolvedValue({ ...stalled, worker_alive: true, stalled: false });
    await userEvent.click(within(notice).getByRole("button", { name: "再檢查一次" }));
    await waitFor(() => expect(within(panel).queryByText(/背景程式停了/)).toBeNull());
    expect(screen.getByRole("button", { name: /生成素材排隊中/ })).toBeTruthy();
  });

  it("a later poll failure replaces the list with the failure, not with nothing", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      vi.mocked(fetchActiveJobs).mockResolvedValueOnce(QUEUE).mockRejectedValue(new Error("down"));
      render(<MemoryRouter><ActiveJobsBell /></MemoryRouter>);
      await screen.findByRole("button", { name: /正在同步成效/ });
      await vi.advanceTimersByTimeAsync(8000);
      expect(await screen.findByRole("button", { name: /背景工作讀取失敗/ })).toBeTruthy();
    } finally {
      vi.useRealTimers();
    }
  });
});

function LocationProbe() {
  return <output aria-label="current path">{useLocation().pathname}</output>;
}
it("navigates inside the SPA with its basename exactly once", async () => {
  vi.mocked(fetchActiveJobs).mockResolvedValue(QUEUE);
  render(<MemoryRouter basename="/app" initialEntries={["/app/inbox"]}><ActiveJobsBell /><LocationProbe /></MemoryRouter>);
  await userEvent.click(await screen.findByRole("button", { name: /正在同步成效/ }));
  const link = screen.getByRole("link", { name: /同步成效・晨光隨行杯/ });
  expect(link.getAttribute("href")).toBe("/app/brands/brd_bughunt/ads/connections");
  await userEvent.click(link);
  expect(screen.getByLabelText("current path").textContent).toBe("/brands/brd_bughunt/ads/connections");
  expect(screen.queryByRole("dialog")).toBeNull();
});
