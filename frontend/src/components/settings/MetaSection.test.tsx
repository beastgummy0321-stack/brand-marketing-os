import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/settingsApi", () => ({ fetchBrandOptions: vi.fn() }));
vi.mock("@/lib/metaApi", () => ({
  bindMetaAccount: vi.fn(),
  connectMetaToken: vi.fn(),
  fetchMetaAccounts: vi.fn(),
  unbindMetaAccount: vi.fn(),
}));

import { fetchBrandOptions } from "@/lib/settingsApi";
import { connectMetaToken, fetchMetaAccounts } from "@/lib/metaApi";
import { MetaSection } from "./MetaSection";

const MISSING_SCOPE =
  "這把權杖看不到廣告帳戶，通常是產生權杖時沒有勾 ads_read 權限。請重新產生一把有勾 ads_read 的權杖再貼上。";

afterEach(() => vi.clearAllMocks());

describe("MetaSection 權杖權限", () => {
  it("貼上前就說明權杖要勾 ads_read，被拒時顯示伺服器給的修正方法", async () => {
    vi.mocked(fetchMetaAccounts).mockResolvedValue({ token_tail: null, accounts: [] });
    vi.mocked(fetchBrandOptions).mockResolvedValue([]);
    vi.mocked(connectMetaToken).mockRejectedValue(new Error(MISSING_SCOPE));
    render(<MetaSection />);

    const input = screen.getByPlaceholderText("貼上 Meta 存取權杖");
    expect(screen.getByText(/要勾選 ads_read 權限/)).toBeTruthy();
    expect(input.getAttribute("aria-describedby")).toBe("meta-token-scope");

    await userEvent.type(input, "EAAbad");
    await userEvent.click(screen.getByRole("button", { name: "連接" }));
    expect(await screen.findByText(MISSING_SCOPE)).toBeTruthy();
  });
});

describe("MetaSection 讀不到 Meta", () => {
  it("Meta 暫時讀不到：說原因，權杖欄和已接的帳戶都還在（drill-10 R4）", async () => {
    const OUTAGE = "Meta 暫時讀不到（代碼 2），這把權杖還沒驗證、沒有存。請稍後再試。";
    vi.mocked(fetchMetaAccounts).mockResolvedValue({
      token_tail: "-jay",
      accounts: [{ id: "acc_1", account_id: "900000000000003", name: "日常萃廣告帳戶", currency: "TWD", connected_at: "", bound_brand_ids: [] }],
    });
    vi.mocked(fetchBrandOptions).mockResolvedValue([]);
    vi.mocked(connectMetaToken).mockRejectedValue(new Error(OUTAGE));
    render(<MetaSection />);

    expect(await screen.findByText("換一把新的權杖")).toBeTruthy();
    const input = screen.getByPlaceholderText("貼上 Meta 存取權杖");
    await userEvent.type(input, "EAAnew");
    await userEvent.click(screen.getByRole("button", { name: "連接" }));
    expect(await screen.findByText(OUTAGE)).toBeTruthy();
    expect(screen.queryByText(/拒絕了這個權杖/)).toBeNull();
    expect(screen.getByPlaceholderText("貼上 Meta 存取權杖")).toHaveProperty("value", "EAAnew");
    expect(screen.getByText("日常萃廣告帳戶")).toBeTruthy();
    expect(screen.getByText("目前使用中的權杖末四碼：-jay")).toBeTruthy();
  });
});


it("acknowledges a connected token until another token is typed", async () => {
  vi.mocked(fetchMetaAccounts).mockResolvedValue({token_tail:null,accounts:[]});
  vi.mocked(fetchBrandOptions).mockResolvedValue([]);
  vi.mocked(connectMetaToken).mockResolvedValue({token_tail:"test",accounts:[]});
  render(<MetaSection/>);
  const field=screen.getByPlaceholderText("貼上 Meta 存取權杖");
  await userEvent.type(field,"test-token");
  await userEvent.click(screen.getByRole("button",{name:"連接"}));
  expect(await screen.findByText("已儲存")).toBeTruthy();
  await userEvent.type(field,"replacement");
  expect(screen.queryByText("已儲存")).toBeNull();
});
