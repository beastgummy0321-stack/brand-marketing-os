/** F51 Contract D: a disabled control says why — `Button` is disabled exactly when it is `busy` or has a
 * `disabledReason`; a reason is printed after it as its accessible description, busy prints nothing. */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Button } from "./button";

describe("Button busy／disabledReason", () => {
  it("a reason disables the button and describes it with one muted sentence", () => {
    render(<Button disabledReason="先選一張圖才能送出。">送出</Button>);
    const button = screen.getByRole("button", { name: "送出" }) as HTMLButtonElement;
    const reason = screen.getByText("先選一張圖才能送出。");
    expect(button.disabled).toBe(true);
    expect(button.getAttribute("aria-describedby")).toBe(reason.id);
    expect(reason.getAttribute("data-slot")).toBe("button-disabled-reason");
    expect(button.getAttribute("aria-busy")).toBeNull();
  });

  it("busy disables without a sentence and marks aria-busy", () => {
    render(<Button busy disabledReason="先選一張圖才能送出。">儲存中…</Button>);
    const button = screen.getByRole("button", { name: "儲存中…" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.getAttribute("aria-busy")).toBe("true");
    expect(button.getAttribute("aria-describedby")).toBeNull();
    expect(screen.queryByText("先選一張圖才能送出。")).toBeNull();
  });

  it("with neither busy nor a reason the button is enabled and undescribed", () => {
    const { rerender } = render(<Button busy={false} disabledReason={null}>送出</Button>);
    const button = () => screen.getByRole("button", { name: "送出" }) as HTMLButtonElement;
    expect(button().disabled).toBe(false);
    expect(button().getAttribute("aria-describedby")).toBeNull();
    rerender(<Button disabledReason="">送出</Button>);
    expect(button().disabled).toBe(false);
  });

  it("keeps the deprecated disabled prop working, and prints a reason passed beside it", () => {
    const { rerender } = render(<Button disabled>送出</Button>);
    expect((screen.getByRole("button", { name: "送出" }) as HTMLButtonElement).disabled).toBe(true);
    rerender(<Button disabled disabledReason="名稱還沒填">送出</Button>);
    expect(screen.getByText("名稱還沒填")).toBeTruthy();
  });

  it("keeps a caller's own aria-describedby beside the reason", () => {
    render(
      <>
        <p id="hint">提示</p>
        <Button aria-describedby="hint" disabledReason="名稱還沒填">送出</Button>
      </>,
    );
    const ids = screen.getByRole("button", { name: "送出" }).getAttribute("aria-describedby")?.split(" ");
    expect(ids).toEqual(["hint", screen.getByText("名稱還沒填").id]);
  });
});
