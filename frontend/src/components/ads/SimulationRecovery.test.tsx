import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { CampaignDetail } from "@/lib/adsApi";
import { readSimulation, saveSimulation, startSimulation, type SimulationDay } from "@/lib/adsSimulationApi";
import { SimulationRecovery } from "./SimulationRecovery";
vi.mock("@/lib/adsSimulationApi", () => ({ readSimulation: vi.fn(), saveSimulation: vi.fn(), startSimulation: vi.fn() }));
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
  expect(await screen.findByRole("alert")).toHaveTextContent("版本衝突");
  expect(screen.getByLabelText("廣告甲 花費")).toHaveValue(0);
  expect(saveSimulation).toHaveBeenCalledWith("brand","c","2026-09-01",0,[{ad_id:"a",spend:0,impressions:0,clicks:0,purchases:0,revenue:0}]);
  expect(startSimulation).not.toHaveBeenCalled();
});
it("requires all fields for a received ad and freezes closed recovery", async () => {
  vi.mocked(readSimulation).mockResolvedValue({...data, closed:true});
  await open();
  expect(screen.getByLabelText("已回收：廣告甲")).toBeDisabled();
  expect(screen.queryByRole("button",{name:"儲存這一天的模擬成效"})).not.toBeInTheDocument();
});
it("does not activate merely by opening the panel or confirmation dialog", async () => {
  vi.mocked(readSimulation).mockResolvedValue({...data,started:false,enabled:false});
  render(<SimulationRecovery brandId="brand" campaign={campaign} onChanged={vi.fn()} onSaved={vi.fn()} />);
  await userEvent.click(screen.getByText("隔離模擬成效回收"));
  await userEvent.click(await screen.findByRole("button",{name:"啟用隔離模擬回收"}));
  expect(await screen.findByRole("dialog")).toHaveTextContent("不能進行真實平台配對");
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
