/** frontend/src/components/intake/steps/StartStep.test.tsx — F31-I01: the start step's unsent text
 * survives leaving the step (unmount) and coming back, per user and brand, and is gone after a
 * successful submit. Before, every field started empty on each mount. No server: the API calls are
 * fakes (same importActual+override pattern as OfferingsStep.test.tsx). */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const workspace = { scope: "usr_1:org_1", refreshBrands: vi.fn() };

vi.mock("@/components/layout/WorkspaceContext", () => ({
  useWorkspace: () => workspace,
}));
vi.mock("@/lib/intakeApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/intakeApi")>("@/lib/intakeApi");
  return { ...actual, submitIntakeStart: vi.fn(), submitIntakeRestart: vi.fn(), fetchIntakeDraft: vi.fn() };
});
vi.mock("@/lib/libraryApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/libraryApi")>("@/lib/libraryApi");
  return { ...actual, setAdvertisingHistory: vi.fn() };
});

import { submitIntakeStart } from "@/lib/intakeApi";
import { setAdvertisingHistory } from "@/lib/libraryApi";
import { StartStep } from "./StartStep";

const mockSubmitIntakeStart = vi.mocked(submitIntakeStart);
const mockSetAdvertisingHistory = vi.mocked(setAdvertisingHistory);

afterEach(() => {
  cleanup();
  localStorage.clear();
  workspace.scope = "usr_1:org_1";
  vi.clearAllMocks();
});

function textbox(name: RegExp): HTMLInputElement {
  return screen.getByRole("textbox", { name }) as HTMLInputElement;
}

describe("StartStep", () => {
  it("離開再回來，沒送出的文字還在，並說明幫你留著", async () => {
    const first = render(<StartStep brandId={null} onSubmitted={vi.fn()} />);
    expect(screen.queryByText("幫你留著上次填的")).toBeNull();
    await userEvent.type(textbox(/品牌名稱/), "虛構品牌");
    await userEvent.type(textbox(/所屬客戶/), "某客戶");
    await userEvent.type(textbox(/描述/), "一句描述");
    await userEvent.click(screen.getByText("研究網址（選填，最多 5 個）"));
    await userEvent.type(screen.getAllByPlaceholderText("https://example.com/...")[0], "https://a.example");
    await userEvent.click(screen.getByLabelText("完全沒投放過"));
    first.unmount();

    render(<StartStep brandId={null} onSubmitted={vi.fn()} />);

    expect(screen.getByText("幫你留著上次填的")).toBeTruthy();
    expect(textbox(/品牌名稱/).value).toBe("虛構品牌");
    expect(textbox(/所屬客戶/).value).toBe("某客戶");
    expect(textbox(/描述/).value).toBe("一句描述");
    expect(screen.getByDisplayValue("https://a.example")).toBeTruthy();
    expect((screen.getByLabelText("完全沒投放過") as HTMLInputElement).checked).toBe(true);
  });

  it("別的使用者看不到這份留著的文字", async () => {
    const first = render(<StartStep brandId={null} onSubmitted={vi.fn()} />);
    await userEvent.type(textbox(/品牌名稱/), "虛構品牌");
    first.unmount();

    workspace.scope = "usr_2:org_1";
    render(<StartStep brandId={null} onSubmitted={vi.fn()} />);

    expect(textbox(/品牌名稱/).value).toBe("");
    expect(screen.queryByText("幫你留著上次填的")).toBeNull();
  });

  it("送出成功後就清掉，下次回來是空的", async () => {
    mockSubmitIntakeStart.mockResolvedValue({ brand_id: "brd_new", quick: false } as never);
    mockSetAdvertisingHistory.mockResolvedValue(undefined as never);
    const onSubmitted = vi.fn();
    const first = render(<StartStep brandId={null} onSubmitted={onSubmitted} />);
    await userEvent.type(textbox(/品牌名稱/), "虛構品牌");
    await userEvent.type(textbox(/描述/), "一句描述");
    await userEvent.click(screen.getByLabelText("完全沒投放過"));
    await userEvent.click(screen.getByRole("button", { name: "建立品牌並開始初掃" }));
    await waitFor(() => expect(onSubmitted).toHaveBeenCalled());
    first.unmount();

    render(<StartStep brandId={null} onSubmitted={vi.fn()} />);

    expect(textbox(/品牌名稱/).value).toBe("");
    expect(textbox(/描述/).value).toBe("");
    expect(screen.queryByText("幫你留著上次填的")).toBeNull();
  });
});
