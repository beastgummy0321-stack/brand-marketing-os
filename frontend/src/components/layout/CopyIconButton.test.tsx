/** F47-I02 (Contract B): copy feedback is visible text — 「已複製」 for 2 s, 「請手動選取複製」 on refusal. F51 Contract S
 * (drill-11 c1-10): 「複製中…」 while the clipboard has not answered; F51 Contract D: nothing to copy says so. */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { COPIED_FEEDBACK_MS, CopyIconButton, NOTHING_TO_COPY } from "./CopyIconButton";
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

  it("says 複製中… while the clipboard has not answered, then 已複製 (an icon-only button is never silent)", async () => {
    let accept: () => void = () => {};
    setClipboard(vi.fn(() => new Promise<void>((resolve) => { accept = resolve; })));
    render(<CopyIconButton ariaLabel="複製內文" getText={() => "認識 Beast Gummy"} />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "複製內文" }));
    });
    const button = screen.getByRole("button", { name: "複製內文" }) as HTMLButtonElement;
    expect(screen.getByText("複製中…")).toBeTruthy();
    expect(button.disabled).toBe(true);
    expect(button.getAttribute("aria-busy")).toBe("true");
    await act(async () => {
      accept();
    });
    expect(screen.queryByText("複製中…")).toBeNull();
    expect(screen.getByText("已複製")).toBeTruthy();
    expect(button.disabled).toBe(false);
  });

  it("with nothing to copy it is greyed out and says 沒有可複製的內容", () => {
    const writeText = vi.fn();
    setClipboard(writeText);
    render(<CopyIconButton ariaLabel="複製說明" disabled getText={() => ""} />);
    const button = screen.getByRole("button", { name: "複製說明" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.getAttribute("aria-describedby")).toBe(screen.getByText(NOTHING_TO_COPY).id);
    fireEvent.click(button);
    expect(writeText).not.toHaveBeenCalled();
  });
});

/* The Dialog close label (F47 Contract B) has no suite of its own; it sits next to the copy button. `Button`'s
 * disabled reason moved to `ui/button.test.tsx` (F51 Contract D: a reason now disables the button). */
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
