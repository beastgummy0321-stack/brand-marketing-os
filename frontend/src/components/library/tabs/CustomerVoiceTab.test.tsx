/** frontend/src/components/library/tabs/CustomerVoiceTab.test.tsx — F50-I16 (Contract J): the extraction placeholders
 * come from the library payload's `customer_voice_jobs` (shape of `routes_library._cv_recent_jobs`), so a reload keeps
 * a running or failed job; `unknown` shows nothing. All API calls are fakes. */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/libraryApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/libraryApi")>("@/lib/libraryApi");
  return { ...actual, fetchCustomerVoiceJob: vi.fn() };
});
vi.mock("../PersonaSection", () => ({ PersonaSection: () => <p>典型客人</p> }));
vi.mock("../panels/CustomerVoicePanel", () => ({
  CustomerVoicePanel: ({ onSubmitted }: { onSubmitted: (jobKey: string, sourceChannel: string) => void }) => (
    <button type="button" onClick={() => onSubmitted("cvjob_new", "ptt")}>送出</button>
  ),
}));
vi.mock("../panels/CustomerVoiceGuidePanel", () => ({ CustomerVoiceGuidePanel: () => null }));

import { fetchCustomerVoiceJob, type LibraryCustomerVoiceJob } from "@/lib/libraryApi";
import { CustomerVoiceTab } from "./CustomerVoiceTab";

const mockJob = vi.mocked(fetchCustomerVoiceJob);
const RUNNING_TEXT = "AI 正在讀這段原話，可以先做別的事，等等收件匣會通知";

function job(over: Partial<LibraryCustomerVoiceJob>): LibraryCustomerVoiceJob {
  return { job_key: "cvjob_1", status: "running", error: null, started_at: "2026-10-05T02:00:00+00:00", ...over };
}

function view(jobs: LibraryCustomerVoiceJob[], onChanged = vi.fn()) {
  const utils = render(<CustomerVoiceTab brandId="brd_x" voices={[]} jobs={jobs} onChanged={onChanged} />);
  return { ...utils, onChanged };
}

beforeEach(() => {
  mockJob.mockReset().mockResolvedValue({ status: "running" });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("CustomerVoiceTab background extraction rows", () => {
  it("mounted with a running job (a reload) shows the placeholder without any click", () => {
    view([job({ status: "running" })]);
    expect(screen.getByText(RUNNING_TEXT)).toBeTruthy();
    expect(screen.queryByText("這個品牌還沒有顧客原話")).toBeNull();
  });

  it("a failed job shows its served error and the existing 重試, which opens the paste panel", () => {
    view([job({ status: "failed", error: "AI 服務暫時忙線，請稍後再試。" })]);
    expect(screen.getByText("AI 服務暫時忙線，請稍後再試。")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "重試" }));
    expect(screen.queryByText("AI 服務暫時忙線，請稍後再試。")).toBeNull();
    expect(screen.getByRole("button", { name: "送出" })).toBeTruthy();
  });

  it("unknown and done jobs show nothing (never 「正在讀」 forever)", () => {
    view([job({ job_key: "cvjob_u", status: "unknown" }), job({ job_key: "cvjob_d", status: "done" })]);
    expect(screen.queryByText(RUNNING_TEXT)).toBeNull();
    expect(screen.getByText("這個品牌還沒有顧客原話")).toBeTruthy();
  });

  it("polls a served running job: unknown removes the row", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockJob.mockResolvedValue({ status: "unknown" });
    view([job({ status: "running" })]);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1100);
    });
    expect(mockJob).toHaveBeenCalledWith("brd_x", "cvjob_1");
    await waitFor(() => expect(screen.queryByText(RUNNING_TEXT)).toBeNull());
  });

  it("polls a served running job: done removes the row and re-reads the library", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockJob.mockResolvedValue({ status: "done", result: {} as never });
    const { onChanged } = view([job({ status: "running" })]);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1100);
    });
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(screen.queryByText(RUNNING_TEXT)).toBeNull();
  });

  it("polls a served running job: failed shows the poll's message", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockJob.mockResolvedValue({ status: "failed", message: "這段原話讀不出重點。" });
    view([job({ status: "running" })]);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1100);
    });
    expect(await screen.findByText("這段原話讀不出重點。")).toBeTruthy();
  });

  it("a just-submitted job shows at once and keeps polling; unmounting stops the poll", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { unmount } = view([]);
    fireEvent.click(screen.getByRole("button", { name: "貼入顧客原話" }));
    fireEvent.click(screen.getByRole("button", { name: "送出" }));
    expect(screen.getByText(RUNNING_TEXT)).toBeTruthy();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1100);
    });
    expect(mockJob).toHaveBeenCalledWith("brd_x", "cvjob_new");
    const calls = mockJob.mock.calls.length;
    unmount();
    await vi.advanceTimersByTimeAsync(5000);
    expect(mockJob.mock.calls.length).toBe(calls);
  });
});
