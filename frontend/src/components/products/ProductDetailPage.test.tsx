import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiResponseError } from "@/lib/http";
import {
  archiveProduct,
  fetchProductDetail,
  fetchProductHandoffPrompt,
  fetchResearchStatus,
  startRescan,
  submitProductHandoff,
  type ProductDetailBundle,
} from "@/lib/productsApi";
import { ProductDetailPage } from "./ProductDetailPage";

// F50-I14: the org is in Taipei whatever zone the test runner is in.
vi.mock("@/components/layout/WorkspaceContext", () => ({
  useWorkspace: () => ({ identity: { org: { id: "org_1", timezone: "Asia/Taipei", today: "2026-10-04" } } }),
}));

vi.mock("@/lib/productsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/productsApi")>("@/lib/productsApi");
  return {
    ...actual,
    archiveProduct: vi.fn(),
    fetchProductDetail: vi.fn(),
    fetchResearchStatus: vi.fn(),
    startRescan: vi.fn(),
    fetchProductHandoffPrompt: vi.fn(),
    submitProductHandoff: vi.fn(),
  };
});

const DETAIL: ProductDetailBundle = {
  id: "p1",
  brand_id: "b1",
  name: "備用商品乙",
  status: "active",
  knowledge_version: 3,
  cards: [
    { key: "facts", title: "產品事實", count: 1, pending: 0 },
    { key: "economics-view", title: "產品經濟數字", count: 0, pending: 0 },
    { key: "rules", title: "適用規則", count: 0, pending: 0 },
    { key: "claims", title: "適用宣稱", count: 0, pending: 0 },
  ],
  latest_source_url: null,
  facts: [{
    id: "f1", fact_type: "core_info", fact_type_label: "核心資訊", label: "核心資訊", value: "咖啡因軟糖",
    status: "confirmed", confirmed_by: "owner@example.com", confirmed_at: "2026-10-01T08:00:00Z", source_reference: null,
  }],
  rules: [],
  claims: [],
};

beforeEach(() => {
  vi.mocked(fetchProductDetail).mockReset().mockResolvedValue(DETAIL);
  vi.mocked(fetchResearchStatus).mockReset().mockResolvedValue({
    status: "done", stage: "", started_at: null, usual_range_text: "", error: null, added_count: null, price_created: false,
  });
  vi.mocked(startRescan).mockReset();
  vi.mocked(fetchProductHandoffPrompt).mockReset().mockResolvedValue({ prompt_text: "請幫我調研這個商品" });
  vi.mocked(submitProductHandoff).mockReset();
  vi.mocked(archiveProduct).mockReset().mockResolvedValue(undefined);
});

function renderPage() {
  render(
    <MemoryRouter>
      <ProductDetailPage brandId="b1" productId="p1" />
    </MemoryRouter>,
  );
}

describe("ProductDetailPage (F47-I03, drill-10 乙 #6 #7)", () => {
  it("「AI 再次調研」 with no URL says what is missing instead of doing nothing", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /AI 再次調研/ }));
    expect((await screen.findByRole("alert")).textContent).toContain("先填要調研的商品頁網址");
    expect(startRescan).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("再次調研網址"), { target: { value: "https://example.com/p" } });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("a pasted reply that yields nothing reads as a failure with the reason and keeps the text", async () => {
    vi.mocked(submitProductHandoff).mockRejectedValue(
      new ApiResponseError("這段回覆讀不出任何產品事實：請確認貼上的是外部 AI 照提示詞回覆的完整內容，再送一次。", 400),
    );
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "深入調研 →" }));
    const reply = screen.getByText("貼上外部 AI 的回覆").closest("label")!.querySelector("textarea")!;
    fireEvent.change(reply, { target: { value: "亂打的一串字" } });
    fireEvent.click(screen.getByRole("button", { name: "送出，讀進來" }));
    expect(await screen.findByText(/讀不出任何產品事實/)).toBeTruthy();
    expect(reply.value).toBe("亂打的一串字");
    expect(screen.queryByText(/貼回完成/)).toBeNull();
  });

  it("a reply whose facts are all on the list already does not claim it added any", async () => {
    vi.mocked(submitProductHandoff).mockResolvedValue({ added_count: 0 });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "深入調研 →" }));
    const reply = screen.getByText("貼上外部 AI 的回覆").closest("label")!.querySelector("textarea")!;
    fireEvent.change(reply, { target: { value: "{\"facts\": []}" } });
    fireEvent.click(screen.getByRole("button", { name: "送出，讀進來" }));
    await waitFor(() => expect(screen.getByText("貼回的事實都已經在清單裡，這次沒有新增。")).toBeTruthy());
  });

  it("shows the confirmer the server resolved (an e-mail, never a user id)", async () => {
    renderPage();
    const details = (await screen.findByText(/詳細（確認人/)).closest("details")!;
    expect(details.textContent).toContain("確認人：owner@example.com");
  });
});

describe("ProductDetailPage 封存 (F47-I05, drill-10 V9)", () => {
  it("封存 asks once and says what happens; 取消 archives nothing, 確定封存 does", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "封存" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("封存產品「備用商品乙」？");
    expect(dialog.textContent).toContain("不會出現在商品清單");
    expect(dialog.textContent).toContain("恢復使用");
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(archiveProduct).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "封存" }));
    fireEvent.click(await screen.findByRole("button", { name: "確定封存" }));
    await waitFor(() => expect(archiveProduct).toHaveBeenCalledWith("b1", "p1"));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("a refused archive keeps the dialog open with the reason", async () => {
    vi.mocked(archiveProduct).mockRejectedValue(new Error("沒有封存（狀態碼 500）"));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "封存" }));
    fireEvent.click(await screen.findByRole("button", { name: "確定封存" }));
    expect((await screen.findByRole("alert")).textContent).toBe("沒有封存（狀態碼 500）");
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("恢復使用 asks nothing and shows a refusal next to the button", async () => {
    vi.mocked(fetchProductDetail).mockResolvedValue({ ...DETAIL, status: "archived" });
    vi.mocked(archiveProduct).mockRejectedValue(new Error("已有同名產品"));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "恢復使用" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect((await screen.findByRole("alert")).textContent).toBe("已有同名產品");
  });
});

describe("ProductDetailPage 經濟數字 (F50-I15, Contract R; drill-11 R6 A3)", () => {
  function renderEconomics() {
    render(
      <MemoryRouter initialEntries={["/?tab=economics-view"]}>
        <ProductDetailPage brandId="b1" productId="p1" />
      </MemoryRouter>,
    );
  }

  it("lists the served sell-ways with the products-page line and links to onboarding step 4; no root-product editor", async () => {
    vi.mocked(fetchProductDetail).mockResolvedValue({
      ...DETAIL,
      // F50-I18: the served card counts the sell-ways (the root row has no money, so it used to read 0).
      cards: DETAIL.cards.map((card) => (card.key === "economics-view" ? { ...card, count: 2 } : card)),
      sell_ways: [
        { id: "sw_one", name: "單盒", shape: "base", price: 399, break_even: 249, offer_labels: [] },
        { id: "sw_three", name: "三盒組", shape: "composed", price: 999, break_even: 668.5, offer_labels: ["組合價 省 198"] },
      ],
    });
    renderEconomics();

    const rows = await waitFor(() => {
      const found = [...document.querySelectorAll('[data-slot="sell-way-row"]')] as HTMLElement[];
      expect(found).toHaveLength(2);
      return found;
    });
    expect(rows.map((r) => r.textContent)).toEqual(["單盒399・打平 249", "三盒組組合價 省 198999・打平 669"]);
    expect(screen.getByRole("button", { name: /^產品經濟數字\s*2$/ })).toBeTruthy();
    expect(screen.getByRole("link", { name: "到建檔第 4 步改 →" }).getAttribute("href")).toBe("/brands/b1/products/p1/onboarding?step=4");
    expect(screen.queryByText("成交率")).toBeNull();
    expect(screen.queryByRole("button", { name: /填寫產品經濟數字|更新數字|確認無誤/ })).toBeNull();
  });

  it("a product with no sell-way says so (an unknown price is never 0) and still links to step 4", async () => {
    vi.mocked(fetchProductDetail).mockResolvedValue({ ...DETAIL, sell_ways: [] });
    renderEconomics();
    expect(await screen.findByText("還沒有賣法")).toBeTruthy();
    expect(screen.getByRole("link", { name: "到建檔第 4 步改 →" })).toBeTruthy();
  });
});

describe("ProductDetailPage on the org clock, no invented job start (F50-I14, Contract K; intake #10)", () => {
  const job = (overrides: Record<string, unknown>) => ({
    status: "running", stage: "讀取網址中", started_at: null, usual_range_text: "30 到 60 秒", error: null,
    added_count: null, price_created: false, ...overrides,
  }) as Awaited<ReturnType<typeof fetchResearchStatus>>;

  it("a fact confirmed at 2026-10-03T23:30Z prints the Taipei day 2026/10/04", async () => {
    vi.mocked(fetchProductDetail).mockResolvedValue({
      ...DETAIL, facts: [{ ...DETAIL.facts[0], confirmed_at: "2026-10-03T23:30:00Z" }],
    });
    renderPage();
    const details = (await screen.findByText(/詳細（確認人/)).closest("details")!;
    expect(details.textContent).toContain("確認時間：2026/10/04");
  });

  it("a research job with status unknown shows no row and no elapsed counter", async () => {
    vi.mocked(fetchResearchStatus).mockResolvedValue(job({ status: "unknown" }));
    renderPage();
    await screen.findByText(/詳細（確認人/);
    await waitFor(() => expect(fetchResearchStatus).toHaveBeenCalled());
    expect(screen.queryByText(/AI 正在調研中/)).toBeNull();
    expect(screen.queryByText(/已等/)).toBeNull();
  });

  it("a running job with no real start says what runs without 「已等 X 秒」", async () => {
    vi.mocked(fetchResearchStatus).mockResolvedValue(job({ started_at: null }));
    renderPage();
    expect(await screen.findByText(/AI 正在調研中：讀取網址中/)).toBeTruthy();
    expect(screen.queryByText(/已等/)).toBeNull();
  });

  it("a running job with a real start counts from that start", async () => {
    vi.mocked(fetchResearchStatus).mockResolvedValue(job({ started_at: "2026-01-01T00:00:00Z" }));
    renderPage();
    expect(await screen.findByText(/已等 \d+ 秒（通常範圍 30 到 60 秒）/)).toBeTruthy();
  });

  it("after 「AI 再次調研」 the row is the server's job state, read again at once — never a made-up start", async () => {
    vi.mocked(startRescan).mockResolvedValue(undefined);
    renderPage();
    fireEvent.change(await screen.findByLabelText("再次調研網址"), { target: { value: "https://example.com/p" } });
    vi.mocked(fetchResearchStatus).mockClear().mockResolvedValue(job({ stage: "伺服器說的階段", started_at: null }));
    fireEvent.click(screen.getByRole("button", { name: /AI 再次調研/ }));
    expect(await screen.findByText(/AI 正在調研中：伺服器說的階段/)).toBeTruthy();
    expect(fetchResearchStatus).toHaveBeenCalled();
    expect(screen.queryByText(/已等/)).toBeNull();
  });
});
