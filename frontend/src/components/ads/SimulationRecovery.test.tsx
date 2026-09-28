import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CampaignDetail } from "@/lib/adsApi";
import { readSimulation, saveSimulation, startSimulation, type SimulationDay } from "@/lib/adsSimulationApi";
import { SimulationRecovery } from "./SimulationRecovery";
vi.mock("@/lib/adsSimulationApi", () => ({ readSimulation: vi.fn(), saveSimulation: vi.fn(), startSimulation: vi.fn() }));
// F36-I09 (ruling G): the component reads the org clock through `useWorkspace().identity.org`; the
// timezone is mutable so one case can move the org to UTC+14 without re-mocking the module.
let orgTimezone = "Asia/Taipei";
vi.mock("@/components/layout/WorkspaceContext", () => ({
  useWorkspace: () => ({
    scope: "user:org", brands: [], brandsLoading: false, brandsError: null, refreshBrands: () => {},
    identity: {
      user: { id: "usr_1", email: "a@example.com" },
      org: { id: "org_test", name: "測試組織", kind: "personal", role: "owner", timezone: orgTimezone, today: "2020-01-01" },
      orgs: [],
    },
  }),
}));
// 2026-02-28 10:30Z: Kiritimati (UTC+14) is already 2026-03-01 00:30; UTC and the test runner zone
// (Asia/Taipei, UTC+8 = 18:30) are still on 2026-02-28. Only `Date` is faked so timers stay real.
const KIRITIMATI_INSTANT = new Date("2026-02-28T10:30:00Z");
function useKiritimati() {
  beforeEach(() => { orgTimezone = "Pacific/Kiritimati"; vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(KIRITIMATI_INSTANT); });
  afterEach(() => { vi.useRealTimers(); orgTimezone = "Asia/Taipei"; });
}
const campaign = { id: "c", name: "測試活動", start_date: "2026-09-01", end_date: "2026-09-07", groups: [{id: "g",name: "共同受眾",ads: [{id:"a",name:"廣告甲",audience_key:"受眾甲"},{id:"b",name:"廣告乙"}]}] } as CampaignDetail;
const data: SimulationDay = { enabled: true, reason: null, started: true, closed: false, day:"2026-09-01",revision:0,saved_at:null,saved_by:null,rows:[],receipts:{} };
beforeEach(() => { vi.clearAllMocks(); vi.mocked(readSimulation).mockResolvedValue(data); });
async function open() {
  render(<SimulationRecovery brandId="brand" campaign={campaign} onChanged={vi.fn()} onSaved={vi.fn()} />);
  await userEvent.click(screen.getByText("隔離模擬成效回收"));
  await screen.findByLabelText("已回收：廣告甲");
}
it("omits missing ads, saves explicit zero and preserves inputs after a failure", async () => {
  await open();
  await userEvent.click(screen.getByLabelText("已回收：廣告甲"));
  for (const label of ["花費","曝光","點擊","轉換數","營收"]) await userEvent.type(screen.getByLabelText(`廣告甲 ${label}`), "0");
  vi.mocked(saveSimulation).mockRejectedValueOnce(new Error("版本衝突，請重新讀取"));
  await userEvent.click(screen.getByRole("button", {name:"儲存這一天的模擬成效"}));
  expect((await screen.findByRole("alert")).textContent).toContain("版本衝突");
  expect((screen.getByLabelText("廣告甲 花費") as HTMLInputElement).value).toBe("0");
  expect(saveSimulation).toHaveBeenCalledWith("brand","c","2026-09-01",0,[{ad_id:"a",spend:0,impressions:0,clicks:0,purchases:0,revenue:0}]);
  expect(startSimulation).not.toHaveBeenCalled();
});
it("requires all fields for a received ad and freezes closed recovery", async () => {
  vi.mocked(readSimulation).mockResolvedValue({...data, closed:true});
  await open();
  expect((screen.getByLabelText("已回收：廣告甲") as HTMLInputElement).disabled).toBe(true);
  expect(screen.queryByRole("button",{name:"儲存這一天的模擬成效"})).toBeNull();
});
it("does not activate merely by opening the panel or confirmation dialog", async () => {
  vi.mocked(readSimulation).mockResolvedValue({...data,started:false,enabled:false});
  render(<SimulationRecovery brandId="brand" campaign={campaign} onChanged={vi.fn()} onSaved={vi.fn()} />);
  await userEvent.click(screen.getByText("隔離模擬成效回收"));
  await userEvent.click(await screen.findByRole("button",{name:"啟用隔離模擬回收"}));
  expect((await screen.findByRole("dialog")).textContent).toContain("不能進行真實平台配對");
  expect(startSimulation).not.toHaveBeenCalled();
});
it("shows read failure and retries without modifying campaign", async () => {
  vi.mocked(readSimulation).mockRejectedValueOnce(new Error("暫時離線"));
  render(<SimulationRecovery brandId="brand" campaign={campaign} onChanged={vi.fn()} onSaved={vi.fn()} />);
  await userEvent.click(screen.getByText("隔離模擬成效回收"));
  await screen.findByText("暫時離線");
  await userEvent.click(screen.getByRole("button",{name:"重新讀取模擬入口"}));
  await waitFor(() => expect(readSimulation).toHaveBeenCalledTimes(2));
  expect(saveSimulation).not.toHaveBeenCalled();
});

describe("F36-I09 組織時鐘：模擬資料日期預設", () => {
  useKiritimati();
  it("沒有開始日時，預設讀組織的今天（UTC+14 已是 3/1），不是瀏覽器的 2/28", async () => {
    render(<SimulationRecovery brandId="brand" campaign={{ ...campaign, start_date: null, end_date: null }} onChanged={vi.fn()} onSaved={vi.fn()} />);
    await userEvent.click(screen.getByText("隔離模擬成效回收"));
    await waitFor(() => expect(readSimulation).toHaveBeenCalledWith("brand", "c", "2026-03-01"));
    expect((await screen.findByLabelText("模擬資料日期") as HTMLInputElement).max).toBe("2026-03-01");
  });
});
