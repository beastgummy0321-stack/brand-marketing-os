/** F47-I02 (Contract B): copy feedback is visible text — 「已複製」 for 2 s, 「請手動選取複製」 on refusal. */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { COPIED_FEEDBACK_MS, CopyIconButton } from "./CopyIconButton";
import { Button } from "./ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "./ui/dialog";

function setClipboard(writeText: (text: string) => Promise<void>) {
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
}

afterEach(() => {
  vi.useRealTimers();
});

describe("CopyIconButton", () => {
  it("says 已複製 for 2 s after the clipboard accepts, then returns to its label", async () => {
    vi.useFakeTimers();
    const writeText = vi.fn().mockResolvedValue(undefined);
    setClipboard(writeText);
    const onResult = vi.fn();
    render(<CopyIconButton label="複製" ariaLabel="複製像素" getText={() => "123456789012345"} onResult={onResult} />);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "複製像素" }));
    });
    expect(writeText).toHaveBeenCalledWith("123456789012345");
    expect(screen.getByText("已複製")).toBeTruthy();
    expect(onResult).toHaveBeenCalledWith(true);

    act(() => vi.advanceTimersByTime(COPIED_FEEDBACK_MS - 100));
    expect(screen.getByText("已複製")).toBeTruthy();
    act(() => vi.advanceTimersByTime(200));
    expect(screen.queryByText("已複製")).toBeNull();
    expect(screen.getByText("複製")).toBeTruthy();
  });

  it("an icon-only button shows 已複製 too, and a refused clipboard says 請手動選取複製 (no optimistic success)", async () => {
    setClipboard(vi.fn().mockResolvedValue(undefined));
    const { unmount } = render(<CopyIconButton ariaLabel="複製邀請連結" getText={() => "https://x"} />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "複製邀請連結" }));
    });
    expect(screen.getByText("已複製")).toBeTruthy();
    unmount();

    setClipboard(vi.fn().mockRejectedValue(new Error("denied")));
    const onResult = vi.fn();
    render(<CopyIconButton label="複製" ariaLabel="複製網址" getText={() => "https://x"} onResult={onResult} />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "複製網址" }));
    });
    expect(screen.getByText("請手動選取複製")).toBeTruthy();
    expect(screen.queryByText("已複製")).toBeNull();
    expect(onResult).toHaveBeenCalledWith(false);
  });
});

/* The other two Contract B shell pieces have no suite of their own; they sit next to the copy button. */
describe("Button disabledReason", () => {
  it("renders one muted sentence as the accessible description only while disabled", () => {
    const { rerender } = render(<Button disabled disabledReason="先選一張圖才能送出。">送出</Button>);
    const button = screen.getByRole("button", { name: "送出" });
    expect(screen.getByText("先選一張圖才能送出。")).toBeTruthy();
    expect(button.getAttribute("aria-describedby")).toBe(screen.getByText("先選一張圖才能送出。").id);
    rerender(<Button disabledReason="先選一張圖才能送出。">送出</Button>);
    expect(screen.queryByText("先選一張圖才能送出。")).toBeNull();
    expect(screen.getByRole("button", { name: "送出" }).getAttribute("aria-describedby")).toBeNull();
  });
});

describe("Dialog close label", () => {
  it("is 關閉, for the corner button and the footer button", () => {
    render(
      <Dialog open>
        <DialogContent>
          <DialogTitle>結案這一期</DialogTitle>
          <DialogDescription>說明</DialogDescription>
          <DialogFooter showCloseButton />
        </DialogContent>
      </Dialog>,
    );
    expect(screen.getAllByRole("button", { name: "關閉" })).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Close" })).toBeNull();
  });
});
