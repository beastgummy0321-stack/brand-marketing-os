/** frontend/src/components/layout/ErrorBoundary.test.tsx — F04-I24: 沒有畫面可以死。一個子
 * 元件爆炸時要看到「這一頁壞了」卡片＋錯誤訊息＋「重新載入」按鈕，不爆的子元件原樣渲染。 */
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ErrorBoundary } from "./ErrorBoundary";

function Bomb(): never {
  throw new Error("測試用爆炸");
}

function Calm() {
  return <div>一切正常</div>;
}

describe("ErrorBoundary", () => {
  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("子元件爆炸時顯示「這一頁壞了」與錯誤訊息，且有重新載入按鈕", () => {
    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>,
    );

    expect(screen.getByText("這一頁壞了")).toBeTruthy();
    expect(screen.getByText("測試用爆炸")).toBeTruthy();
    expect(screen.getByRole("button", { name: "重新載入" })).toBeTruthy();
  });

  it("子元件沒爆炸時原樣渲染", () => {
    render(
      <ErrorBoundary>
        <Calm />
      </ErrorBoundary>,
    );

    expect(screen.getByText("一切正常")).toBeTruthy();
    expect(screen.queryByText("這一頁壞了")).toBeNull();
  });
});
