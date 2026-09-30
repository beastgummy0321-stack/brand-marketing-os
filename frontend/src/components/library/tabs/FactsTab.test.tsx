/** frontend/src/components/library/tabs/FactsTab.test.tsx — F07-I12：`VisualSpecWarnings`
 * mounts at the top of 品牌事實, wired with the tab's own `brandId`, before any fact section. */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/workbench", () => ({
  VisualSpecWarnings: ({ brandId }: { brandId: string }) => (
    <div data-testid="visual-spec-warnings">{brandId}</div>
  ),
}));

import type { LibraryBrandFact } from "@/lib/libraryApi";
import { FactsTab } from "./FactsTab";

function fact(overrides: Partial<LibraryBrandFact>): LibraryBrandFact {
  return {
    id: "bft_1",
    fact_type: "positioning",
    fact_type_label: "定位",
    fact_key: null,
    fact_key_label: null,
    label: "單一產區可追溯",
    value: "茶葉全部來自同一個產區",
    status: "confirmed",
    confirmed_by: "本人",
    confirmed_at: "2026-09-01T00:00:00+00:00",
    stale_label: null,
    source_reference: null,
    ...overrides,
  };
}

describe("FactsTab 掛載 VisualSpecWarnings（F07-I12）", () => {
  it("在分頁最上面，帶著這個分頁自己的 brandId，出現在「品牌事實」標題之前", () => {
    render(<FactsTab brandId="brd_1" facts={[]} onChanged={() => {}} />);

    const stub = screen.getByTestId("visual-spec-warnings");
    expect(stub.textContent).toBe("brd_1");

    const heading = screen.getByText("品牌事實");
    // stub 在 heading 之前：heading 相對 stub 是 DOCUMENT_POSITION_FOLLOWING。
    const position = stub.compareDocumentPosition(heading);
    expect(Boolean(position & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true);
  });
});

describe("證據事實（F38-I01）", () => {
  it("a proof row prints its kind label right after the type badge", () => {
    render(
      <FactsTab
        brandId="brd_1"
        facts={[
          fact({}),
          fact({
            id: "bft_2",
            fact_type: "proof",
            fact_type_label: "證據",
            fact_key: "customer_review",
            fact_key_label: "顧客評論原話",
            label: "PChome 4.8 星、1,200 則評論",
          }),
        ]}
        onChanged={() => {}}
      />,
    );
    const kind = screen.getByText("顧客評論原話");
    const badge = screen.getAllByText("證據").find((el) => el.tagName !== "BUTTON");
    expect(badge).toBeDefined();
    expect(badge!.nextElementSibling).toBe(kind);
    // a non-proof row carries no kind text
    expect(screen.queryByText("檢驗報告／認證")).toBeNull();
  });

  it("the panel asks 「哪一種證據？」 only for proof and blocks saving without a kind", () => {
    render(<FactsTab brandId="brd_1" facts={[]} onChanged={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "新增品牌事實" }));
    expect(screen.queryByText("哪一種證據？")).toBeNull();

    const typeSelect = screen.getByDisplayValue("請選擇");
    fireEvent.change(typeSelect, { target: { value: "proof" } });
    expect(screen.getByText("哪一種證據？")).toBeTruthy();
    expect(screen.getByPlaceholderText("例如「PChome 4.8 星、1,200 則評論」")).toBeTruthy();

    fireEvent.change(screen.getByPlaceholderText("例如「PChome 4.8 星、1,200 則評論」"), {
      target: { value: "PChome 4.8 星" },
    });
    fireEvent.submit(screen.getByRole("button", { name: "新增這條事實" }).closest("form")!);
    expect(screen.getByText("請選擇哪一種證據。")).toBeTruthy();

    fireEvent.change(typeSelect, { target: { value: "tone" } });
    expect(screen.queryByText("哪一種證據？")).toBeNull();
  });
});

describe("全店政策（F42-I01）", () => {
  it("a policy row shows its type badge and name, no internal key and no 修改", () => {
    render(
      <FactsTab
        brandId="brd_1"
        facts={[
          fact({}),
          fact({
            id: "bft_3",
            fact_type: "policy",
            fact_type_label: "全店政策",
            fact_key: "ship_threshold",
            fact_key_label: "ship_threshold",
            label: "滿額免運",
            value: "滿 NT$999 免運",
          }),
        ]}
        onChanged={() => {}}
      />,
    );
    expect(screen.getAllByText("全店政策").some((el) => el.tagName !== "BUTTON")).toBe(true);
    expect(screen.getByText("滿額免運")).toBeTruthy();
    expect(screen.getByText("滿 NT$999 免運")).toBeTruthy();
    expect(screen.queryByText("ship_threshold")).toBeNull();
    // only the positioning row can be edited here
    expect(screen.getAllByRole("button", { name: "修改" })).toHaveLength(1);
  });

  it("the new-fact panel does not offer 全店政策", () => {
    render(<FactsTab brandId="brd_1" facts={[]} onChanged={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "新增品牌事實" }));
    const options = screen.getAllByRole("option").map((o) => o.textContent);
    expect(options).toContain("證據");
    expect(options).not.toContain("全店政策");
  });
});
