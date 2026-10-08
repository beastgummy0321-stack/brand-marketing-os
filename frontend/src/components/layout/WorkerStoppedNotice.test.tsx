import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { WorkerStoppedNotice } from "./WorkerStoppedNotice";

it("unknown explains uncertainty without claiming the worker stopped or is alive", async () => {
  const recheck = vi.fn().mockResolvedValue(undefined);
  render(<WorkerStoppedNotice state="unknown" onRecheck={recheck} />);
  expect(screen.getByRole("alert").textContent).toContain("背景程式狀態無法確認");
  expect(screen.getByRole("alert").textContent).not.toMatch(/停了|重新啟動|自動接著做/);
  await userEvent.click(screen.getByRole("button", { name: "再檢查一次" }));
  expect(recheck).toHaveBeenCalledTimes(1);
});

it("a confirmed stop retains the existing recovery action and layout", () => {
  render(<WorkerStoppedNotice state="stopped" onRecheck={vi.fn()} />);
  expect(screen.getByRole("alert").textContent).toContain("背景程式停了");
  expect(screen.getByRole("alert").getAttribute("data-slot")).toBe("worker-stopped");
});
