import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { InboxItem } from "@/lib/inboxApi";
import { InboxItemDetail } from "./InboxItemCard";

// F50-I14: the org is in Taipei whatever zone the test runner is in.
vi.mock("@/components/layout/WorkspaceContext", () => ({
  useWorkspace: () => ({ identity: { org: { id: "org_1", timezone: "Asia/Taipei", today: "2026-09-18" } } }),
}));

const ITEM: InboxItem = {
  id: "alert-1",
  brand_id: "brand-1",
  brand_name: "測試品牌",
  category: "budget",
  category_label: "預算提醒",
  severity: "rule_warning",
  message: "請檢查本週預算。",
  action_url: "/brands/brand-1/cockpit",
  resolved_at: null,
};

function detail(item: InboxItem, variant: "open" | "done", onResolve = vi.fn()) {
  return render(<MemoryRouter><InboxItemDetail item={item} variant={variant} resolving={false} busy={false} onResolve={onResolve} /></MemoryRouter>);
}

describe("InboxItemDetail 處理動作", () => {
  it("待處理事項清楚標示標記動作，保留詳情連結並呼叫既有 callback", async () => {
    const onResolve = vi.fn();
    detail(ITEM, "open", onResolve);
    expect(screen.getByRole("link", { name: /前往詳情/ })).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "標記已處理" }));
    expect(onResolve).toHaveBeenCalledWith("alert-1");
  });

  it("已處理狀態不宣稱事項已結案", () => {
    detail({ ...ITEM, resolved_at: "2026-09-18T02:00:00Z" }, "done");
    expect(screen.getByText("已標記處理於 2026/09/18 10:00")).toBeTruthy();
    expect(screen.queryByText(/結案於/)).toBeNull();
  });

  it("prints the resolved instant on the org's clock: 23:30Z is the next day in Taipei", () => {
    detail({ ...ITEM, resolved_at: "2026-10-03T23:30:00Z" }, "done");
    expect(screen.getByText("已標記處理於 2026/10/04 07:30")).toBeTruthy();
  });
});
