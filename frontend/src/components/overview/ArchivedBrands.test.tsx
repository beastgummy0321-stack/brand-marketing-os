/** frontend/src/components/overview/ArchivedBrands.test.tsx — the overview's folded 「已封存的品牌（N）」 section (F50-I17):
 * hidden at 0; 「還原」 posts the restore, re-reads the list and refreshes the workspace brands; a failed restore keeps
 * the row with the server's sentence. No server: the API calls are fakes. */
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, fetchArchivedBrands: vi.fn() };
});
vi.mock("@/lib/libraryApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/libraryApi")>("@/lib/libraryApi");
  return { ...actual, restoreBrand: vi.fn() };
});

import { fetchArchivedBrands } from "@/lib/api";
import { restoreBrand } from "@/lib/libraryApi";
import { ArchivedBrands } from "./ArchivedBrands";

const mockList = vi.mocked(fetchArchivedBrands);
const mockRestore = vi.mocked(restoreBrand);
const oldTea = { brand_id: "brd_tea", name: "山嵐茶研所（舊品牌）" };

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe("ArchivedBrands", () => {
  it("renders nothing when the org has no archived brand", async () => {
    mockList.mockResolvedValue([]);
    const { container } = render(<ArchivedBrands onRestored={vi.fn()} />);
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(1));
    expect(container.innerHTML).toBe("");
  });

  it("lists archived brands folded; 「還原」 restores, re-reads and refreshes the workspace brands", async () => {
    mockList.mockResolvedValueOnce([oldTea]).mockResolvedValueOnce([]);
    mockRestore.mockResolvedValue(undefined);
    const onRestored = vi.fn();
    render(<ArchivedBrands onRestored={onRestored} />);

    const summary = await screen.findByText("已封存的品牌（1）");
    const fold = summary.closest("details") as HTMLElement;
    expect(fold.hasAttribute("open")).toBe(false);
    await userEvent.click(summary);
    const row = within(fold).getByText("山嵐茶研所（舊品牌）").closest("[data-slot=archived-brand]") as HTMLElement;
    await userEvent.click(within(row).getByRole("button", { name: "還原" }));

    expect(mockRestore).toHaveBeenCalledWith("brd_tea");
    await waitFor(() => expect(onRestored).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.queryByText(/已封存的品牌/)).toBeNull());
  });

  it("a failed 「還原」 keeps the row and shows the server's sentence on it", async () => {
    mockList.mockResolvedValue([oldTea]);
    mockRestore.mockRejectedValue(new Error("這個品牌沒有封存，不用還原。"));
    const onRestored = vi.fn();
    render(<ArchivedBrands onRestored={onRestored} />);

    await userEvent.click(await screen.findByText("已封存的品牌（1）"));
    const row = screen.getByText("山嵐茶研所（舊品牌）").closest("[data-slot=archived-brand]") as HTMLElement;
    await userEvent.click(within(row).getByRole("button", { name: "還原" }));

    expect((await within(row).findByRole("alert")).textContent).toBe("這個品牌沒有封存，不用還原。");
    expect(within(row).getByRole("button", { name: "還原" }).hasAttribute("disabled")).toBe(false);
    expect(onRestored).not.toHaveBeenCalled();
  });

  it("a failed read says so instead of hiding the section silently", async () => {
    mockList.mockRejectedValue(new Error("讀不到已封存的品牌（狀態碼 500）"));
    render(<ArchivedBrands onRestored={vi.fn()} />);
    expect((await screen.findByRole("alert")).textContent).toContain("狀態碼 500");
  });
});
