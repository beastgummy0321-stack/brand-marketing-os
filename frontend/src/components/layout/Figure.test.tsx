/** F51 Contract F: `Figure` prints a value with its basis read from `GET /api/figures` — unknown never as 0, money
 * with its own currency, a ratio with its caption (and `alt` beside it), no caption before the bases load. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/http", async () => {
  const actual = await vi.importActual<typeof import("@/lib/http")>("@/lib/http");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "@/lib/http";
import { Figure } from "./Figure";

const mockApiFetch = vi.mocked(apiFetch);

/** The served table's shape (`app/core/figures.py::BASES`), the rows this suite prints. */
const BASES = {
  roas_all_spend: { label: "保守", formula: "營收 ÷ 全部花費", unit: "ratio" },
  roas_tracked_spend: { label: "樂觀", formula: "營收 ÷ 有追到營收的那部分花費", unit: "ratio" },
  earn_after_cost_and_ads: { label: "扣掉商品成本和廣告費", formula: "成交數 ×（售價 − 成本含運）− 廣告費", unit: "money" },
};

function served(body: unknown = { bases: BASES }) {
  return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
}

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("Figure", () => {
  it("prints an unknown value as 不明 (or the payload's reason), never 0", async () => {
    mockApiFetch.mockResolvedValue(served());
    const { unmount } = render(wrap(<Figure basis="roas_all_spend" value={null} />));
    await screen.findByText("保守");
    expect(screen.getByText("不明")).toBeTruthy();
    expect(screen.queryByText(/0\.00x|^0$/)).toBeNull();
    unmount();

    render(wrap(<Figure basis="earn_after_cost_and_ads" value={null} currency="TWD" unknown="成本未填" />));
    expect(await screen.findByText("成本未填")).toBeTruthy();
  });

  it("prints money with its own currency and the basis caption", async () => {
    mockApiFetch.mockResolvedValue(served());
    render(wrap(<Figure basis="earn_after_cost_and_ads" value={-1234.4} currency="USD" />));
    expect(await screen.findByText("扣掉商品成本和廣告費")).toBeTruthy();
    expect(screen.getByText("-1,234 USD")).toBeTruthy();
    expect(screen.queryByText(/NT\$/)).toBeNull();
  });

  it("prints a ratio with its caption, the formula behind ?, and the alt basis beside it", async () => {
    mockApiFetch.mockResolvedValue(served());
    const { container } = render(wrap(<Figure basis="roas_all_spend" value={2.1} alt={{ basis: "roas_tracked_spend", value: 2.454 }} />));
    expect(await screen.findByText("保守")).toBeTruthy();
    expect(screen.getByText("樂觀")).toBeTruthy();
    expect(screen.getByText("2.10x")).toBeTruthy();
    expect(screen.getByText("2.45x")).toBeTruthy();
    expect(screen.getByRole("button", { name: "保守怎麼算：營收 ÷ 全部花費" })).toBeTruthy();
    expect(container.textContent).toMatch(/保守.*2\.10x.*・.*樂觀.*2\.45x/);
    expect(mockApiFetch).toHaveBeenCalledWith("/api/figures");
  });

  it("prints the value without a caption while the bases load", async () => {
    let answer: (res: Response) => void = () => {};
    mockApiFetch.mockReturnValue(new Promise<Response>((resolve) => { answer = resolve; }));
    render(wrap(<Figure basis="roas_all_spend" value={1.5} />));
    expect(screen.getByText("1.50x")).toBeTruthy();
    expect(screen.queryByText("保守")).toBeNull();
    answer(served());
    await waitFor(() => expect(screen.getByText("保守")).toBeTruthy());
  });

  it("reads the bases once for every figure on the page", async () => {
    mockApiFetch.mockResolvedValue(served());
    render(wrap(<><Figure basis="roas_all_spend" value={1} /><Figure basis="roas_tracked_spend" value={2} /></>));
    await screen.findByText("樂觀");
    expect(mockApiFetch).toHaveBeenCalledTimes(1);
  });
});
