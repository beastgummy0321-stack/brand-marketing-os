import {act, fireEvent, render, screen, waitFor} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {MemoryRouter} from "react-router-dom";
import {afterEach, expect, it, vi} from "vitest";
import {getCoordinateLearnings, type CoordinateLearnings} from "@/lib/adsLearningsApi";
import {getWizardOptions} from "@/lib/adsWizardApi";
import {LearningsTab} from "./LearningsTab";
import {QualifiedLearningList} from "./QualifiedLearningList";
import {libraryEvidenceFixture, libraryOptionsFixture} from "./learningEvidence.fixtures";

vi.mock("@/lib/adsWizardApi", () => ({getWizardOptions: vi.fn()}));
vi.mock("@/lib/adsLearningsApi", () => ({getCoordinateLearnings: vi.fn()}));
const options = vi.mocked(getWizardOptions);
const readings = vi.mocked(getCoordinateLearnings);
const mainName = "用可參考資料規劃下一期 →";
afterEach(() => vi.resetAllMocks());
function view(data = libraryEvidenceFixture()) {
  options.mockResolvedValue({...libraryOptionsFixture, products: [...libraryOptionsFixture.products,
    {...libraryOptionsFixture.products[0], id: "prd_second", name: "第二商品 · 單件"}]});
  if (!readings.getMockImplementation()) readings.mockResolvedValue(libraryEvidenceFixture());
  return render(<MemoryRouter><LearningsTab brandId="brd_f53_ui" state={{status: "ready", data}} onRetry={vi.fn()}/></MemoryRouter>);
}
function choose(id: string) {
  const fold = screen.getByRole("button", {name: "下一期商品範圍"});
  if (fold.getAttribute("aria-expanded") !== "true") fireEvent.click(fold);
  fireEvent.change(screen.getByRole("combobox", {name: "選擇商品"}), {target: {value: id}});
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return {promise, resolve};
}
it("uses scoped qualification independently of global ranks, and filters only served use states", async () => {
  view();
  expect((await screen.findByRole("link", {name: mainName})).getAttribute("href")).toBe("/brands/brd_f53_ui/ads/new?sell_way=prd_fixture");
  expect(readings).toHaveBeenCalledWith("brd_f53_ui", {sellWayId: "prd_fixture"}, expect.any(AbortSignal));
  expect(screen.getByText("2 條可參考 · 其餘資料保留在歷史")).toBeTruthy();
  expect(screen.getAllByText("本商品不適用。")).toHaveLength(1);
  expect(document.querySelectorAll("[data-slot=library-learning-row]")).toHaveLength(6);
  fireEvent.click(screen.getByRole("button", {name: "可參考"}));
  expect(document.querySelectorAll("[data-slot=library-learning-row]")).toHaveLength(2);
  fireEvent.click(screen.getByRole("button", {name: "歷史與其他資料"}));
  expect(document.querySelectorAll("[data-slot=library-learning-row]")).toHaveLength(4);
  fireEvent.click(screen.getByRole("button", {name: "每期廣告排名"}));
  expect(screen.getByRole("table", {name: "九月夜跑活動 每則廣告排名"})).toBeTruthy();
  expect(screen.getByText("花 1,200・成交 6・每筆 200")).toBeTruthy();
});
it("retains the explicit draft and same-scope last good read through failure/retry; refresh does not select next", async () => {
  view();
  await screen.findByRole("link", {name: mainName});
  choose("prd_second");
  const second = libraryEvidenceFixture();
  second.evidence_context.scope_product_id = "prd_second";
  second.evidence_context.scope_label = "第二商品 · 單件";
  second.next = null;
  readings.mockResolvedValue(second);
  // The first in-flight response belongs to the former scope and cannot certify this selection.
  fireEvent.click(screen.getByRole("button", {name: "重新讀取 ↻"}));
  await waitFor(() => expect(screen.getByRole("link", {name: mainName}).getAttribute("href")).toContain("sell_way=prd_second"));
  readings.mockRejectedValueOnce(new Error("來源暫時無法讀取"));
  fireEvent.click(screen.getByRole("button", {name: "重新讀取 ↻"}));
  expect((await screen.findByRole("alert")).textContent).toContain("保留同商品上次讀取");
  expect(screen.getByRole("combobox", {name: "選擇商品"})).toHaveProperty("value", "prd_second");
  expect(document.querySelectorAll("[data-slot=library-learning-row]")).toHaveLength(6);
  expect(screen.queryByRole("link", {name: mainName})).toBeNull();
  fireEvent.click(screen.getByRole("button", {name: "重新讀取"}));
  expect((await screen.findByRole("link", {name: mainName})).getAttribute("href")).toContain("sell_way=prd_second");
  expect(screen.getByRole("combobox", {name: "選擇商品"})).toHaveProperty("value", "prd_second");
});
it("rejects late former-product responses and scope mismatch without promoting unknown to empty", async () => {
  const old = deferred<CoordinateLearnings>();
  readings.mockImplementation((_brand, filter) => filter?.sellWayId === "prd_fixture" ? old.promise : Promise.resolve(libraryEvidenceFixture()));
  view();
  await screen.findByText("反光夜跑背心 · 單件", {selector: "b"});
  choose("prd_second");
  expect((await screen.findByRole("alert")).textContent).toContain("商品範圍尚未核實");
  await act(async () => old.resolve(libraryEvidenceFixture()));
  expect(screen.queryByRole("link", {name: mainName})).toBeNull();
  expect(document.querySelectorAll("[data-slot=library-learning-row]")).toHaveLength(0);
  expect(screen.queryByText("還沒有學習紀錄")).toBeNull();
});
it("unknown next requires explicit valid selection; a verified empty context stays a cold start", async () => {
  const empty = libraryEvidenceFixture();
  empty.next = null;
  empty.evidence_context.items = [];
  empty.evidence_context.eligible_count = 0;
  empty.campaigns = [];
  readings.mockResolvedValue(empty);
  view(empty);
  await waitFor(() => expect(options).toHaveBeenCalled());
  expect(screen.queryByRole("link", {name: mainName})).toBeNull();
  expect(screen.queryByText("還沒有學習紀錄")).toBeNull();
  choose("prd_fixture");
  expect(await screen.findByText("還沒有學習紀錄")).toBeTruthy();
  expect(await screen.findByRole("link", {name: mainName})).toBeTruthy();
});
it("preserves null versus zero and exact source metadata; keyboard Escape returns focus", async () => {
  const user = userEvent.setup();
  view();
  await screen.findByRole("link", {name: mainName});
  const triggers = screen.getAllByRole("button", {name: "查看 →"});
  triggers[3].focus();
  await user.keyboard("{Enter}");
  expect((await screen.findByRole("dialog")).textContent).toContain("樣本尚未完整核實");
  expect(screen.getByRole("dialog").textContent).toContain("來源未提供，尚未核實");
  await user.keyboard("{Escape}");
  await waitFor(() => expect(document.activeElement).toBe(triggers[3]));
  triggers[4].focus();
  await user.keyboard("{Enter}");
  expect((await screen.findByRole("dialog")).textContent).toContain("0 筆");
  expect(screen.getByRole("dialog").textContent).toContain("演練資料");
});
it("includes ranked-only served evidence with same-ID dedupe; contrary status remains server-owned", () => {
  const data = libraryEvidenceFixture();
  const first = data.campaigns[0].rows[0].evidence;
  first.contrary_count = 1;
  first.use_state = "revalidation";
  first.reason_labels = ["已有反向觀察，需重新核對。"];
  data.evidence_context.items = [data.evidence_context.items[1]];
  render(<QualifiedLearningList data={data} onRetry={vi.fn()}/>);
  expect(document.querySelectorAll("[data-slot=library-learning-row]")).toHaveLength(2);
  expect(screen.getByText("需重新核對")).toBeTruthy();
  expect(screen.getByText("已有反向觀察，需重新核對。")).toBeTruthy();
});
