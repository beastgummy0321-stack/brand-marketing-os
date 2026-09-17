import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { readComparison, confirmComparison, type ComparisonState } from "@/lib/adsExperimentApi";
import { ExperimentPlan } from "./ExperimentPlan";
vi.mock("@/lib/adsExperimentApi",()=>({readComparison:vi.fn(),confirmComparison:vi.fn()}));
const proposal = {fingerprint:"fp",hypothesis:"只改開場",variable:"開場",variants:[{ad_id:"a",name:"甲",value:"問句"},{ad_id:"b",name:"乙",value:"敘述"}],shared:{group:"同組",audience:"同受眾",channel:"meta",daily_budget:500,objective:"購買"},metric_label:"每次轉換成本",window:{start:"2026-09-01",end:"2026-09-07"},stop:"期間結束停止收樣",limitation:"觀察比較，不是因果證據"};
const state: ComparisonState = {proposal,missing:null,confirmed:null,stale:false,closed:false,simulation:true,result:{verdict:"看不出",reason:"請先確認",values:[]}};
beforeEach(()=>{vi.clearAllMocks();vi.mocked(readComparison).mockResolvedValue(state);});
function mount(){render(<ExperimentPlan brandId="brand" campaignId="c" refreshKey={0} onViewPlan={vi.fn()} />);}
it("keeps a proposal read-only until conditions are checked and confirmed",async()=>{
  mount();
  const button = await screen.findByRole("button",{name:"確認這份比較計畫"});
  expect((button as HTMLButtonElement).disabled).toBe(true);
  expect(confirmComparison).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("checkbox"));
  vi.mocked(confirmComparison).mockResolvedValue({...state,confirmed:{...proposal,confirmed_at:"now",confirmed_by:"me",timing:"before_data"}});
  await userEvent.click(button);
  await screen.findByText("已保存的確認紀錄");
  expect(confirmComparison).toHaveBeenCalledWith("brand","c","fp");
  expect(screen.queryByRole("button",{name:"確認這份比較計畫"})).toBeNull();
});
it("shows a missing-control explanation rather than a fabricated plan",async()=>{
  vi.mocked(readComparison).mockResolvedValue({...state,proposal:null,missing:"缺少合格對照"});
  mount();await screen.findByText("缺少合格對照");
  expect(screen.queryByRole("checkbox")).toBeNull();
  expect(screen.getByRole("button",{name:"前往投放結構補對照"})).toBeTruthy();
});
it("marks stale confirmation and retrospective timing clearly",async()=>{
  vi.mocked(readComparison).mockResolvedValue({...state,stale:true,confirmed:{...proposal,confirmed_at:"now",confirmed_by:"me",timing:"retrospective"}});
  mount();await screen.findByText(/原確認已過期/);
  await userEvent.click(screen.getByText("已保存的確認紀錄（已過期）"));
  expect(screen.getByText(/事後觀察，不是事前實驗/)).toBeTruthy();
  expect((screen.getByRole("button",{name:"確認這份比較計畫"}) as HTMLButtonElement).disabled).toBe(true);
});
it("keeps failed confirmation visible and allows retry",async()=>{
  mount();await screen.findByRole("checkbox");
  await userEvent.click(screen.getByRole("checkbox"));
  vi.mocked(confirmComparison).mockRejectedValue(new Error("提案條件已變更"));
  await userEvent.click(screen.getByRole("button",{name:"確認這份比較計畫"}));
  expect((await screen.findByRole("alert")).textContent).toContain("已變更");
  expect(screen.getByRole("button",{name:"重新讀取比較提案"})).toBeTruthy();
});
