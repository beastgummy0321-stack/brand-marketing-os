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
