/** frontend/src/components/library/tabs/FactsTab.test.tsx — F07-I12：`VisualSpecWarnings`
 * mounts at the top of 品牌事實, wired with the tab's own `brandId`, before any fact section. */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/workbench", () => ({
  VisualSpecWarnings: ({ brandId }: { brandId: string }) => (
    <div data-testid="visual-spec-warnings">{brandId}</div>
  ),
}));

import { FactsTab } from "./FactsTab";

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
