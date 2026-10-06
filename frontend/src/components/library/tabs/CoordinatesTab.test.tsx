import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

const mountedInteraction = vi.hoisted(() => ({ run: null as (() => void) | null }));

vi.mock("../shared/Badge", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../shared/Badge")>();
  const { useLayoutEffect } = await import("react");
  return { Badge: ({ children }: { children: ReactNode }) => {
    // Deliver an input as soon as ready rows mount, before passive default-selection effects.
    useLayoutEffect(() => { queueMicrotask(() => mountedInteraction.run?.()); }, []);
    return <actual.Badge>{children}</actual.Badge>;
  } };
});

vi.mock("@/lib/coordinatesApi", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/coordinatesApi")>(),
  fetchCoordinates: vi.fn(),
  createCoordinate: vi.fn(),
  setCoordinateDisabled: vi.fn(),
}));

import { createCoordinate, fetchCoordinates, setCoordinateDisabled, type Coordinate } from "@/lib/coordinatesApi";
import { CoordinatesTab } from "./CoordinatesTab";

const fetchMock = vi.mocked(fetchCoordinates);
const toggleMock = vi.mocked(setCoordinateDisabled);
const createMock = vi.mocked(createCoordinate);

function coordinate(id: string, category: string | null, dimension: Coordinate["dimension"] = "angle"): Coordinate {
  return { id, category, dimension, key: id, label: `${id} coordinate`, canonical_key: null,
    attributes: {}, disabled_at: null, rejected: false };
}

const rows = [coordinate("first", "第一類"), coordinate("second", "第二類"),
  coordinate("proof-first", "證明一", "proof"), coordinate("proof-second", "證明二", "proof")];

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

async function selectCategory(category = "第二類") {
  const select = await screen.findByRole("combobox", { name: "分類" });
  fireEvent.change(select, { target: { value: category } });
  await screen.findByText(rows.find(row => row.category === category)!.label);
  return select as HTMLSelectElement;
}

beforeEach(() => {
  vi.resetAllMocks();
  mountedInteraction.run = null;
  fetchMock.mockResolvedValue(rows);
});

describe("coordinate context survives saves (F52-I15)", () => {
  it("does not let the initial category normalization overwrite an immediate user selection", async () => {
    fetchMock.mockResolvedValue(rows.map(row => ({ ...row, attributes: { funnel_stage: "test stage" } })));
    const observed: string[] = [];
    mountedInteraction.run = () => {
      mountedInteraction.run = null;
      const select = screen.getByRole("combobox", { name: "分類" }) as HTMLSelectElement;
      observed.push(select.value);
      fireEvent.change(select, { target: { value: "第二類" } });
      observed.push(select.value);
    };
    render(<CoordinatesTab brandId="brand-one" />);
    await screen.findByText("second coordinate");
    expect(observed).toEqual(["第一類", "第二類"]);
    expect((screen.getByRole("combobox", { name: "分類" }) as HTMLSelectElement).value).toBe("第二類");
  });

  it("keeps the selected category and toggle focus through a delayed refresh", async () => {
    const refresh = deferred<Coordinate[]>();
    fetchMock.mockResolvedValueOnce(rows).mockReturnValueOnce(refresh.promise);
    const saved = { ...rows[1], disabled_at: "2026-10-06T00:00:00Z" };
    toggleMock.mockResolvedValue(saved);
    render(<CoordinatesTab brandId="brand-one" />);
    const select = await selectCategory();
    const toggle = screen.getByRole("checkbox", { name: "啟用" });
    toggle.focus();
    fireEvent.click(toggle);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("combobox", { name: "分類" })).toBe(select);
    expect(select.value).toBe("第二類");
    await act(async () => refresh.resolve(rows.map(row => row.id === saved.id ? saved : row)));
    const updated = await screen.findByRole("checkbox", { name: "已停用" });
    expect((updated as HTMLInputElement).checked).toBe(false);
    await waitFor(() => expect(document.activeElement).toBe(updated));
    expect(select.value).toBe("第二類");
  });

  it("keeps the dimension, category and unsaved state after a rejected toggle, then retries", async () => {
    toggleMock.mockRejectedValueOnce(new Error("儲存失敗")).mockResolvedValueOnce({ ...rows[3], disabled_at: "saved" });
    fetchMock.mockResolvedValueOnce(rows).mockResolvedValueOnce(rows.map(row => row.id === rows[3].id ? { ...row, disabled_at: "saved" } : row));
    render(<CoordinatesTab brandId="brand-one" />);
    await screen.findByRole("button", { name: /證明/ });
    fireEvent.click(screen.getByRole("button", { name: /證明/ }));
    const select = await selectCategory("證明二");
    const toggle = screen.getByRole("checkbox", { name: "啟用" });
    toggle.focus();
    fireEvent.click(toggle);
    await screen.findByText("儲存失敗");
    expect(select.value).toBe("證明二");
    expect((toggle as HTMLInputElement).checked).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(document.activeElement).toBe(toggle);
    fireEvent.click(toggle);
    await screen.findByRole("checkbox", { name: "已停用" });
    expect((screen.getByRole("combobox", { name: "分類" }) as HTMLSelectElement).value).toBe("證明二");
    expect(toggleMock).toHaveBeenLastCalledWith("brand-one", "proof-second", true);
  });

  it("keeps the category and failed create inputs, and returns focus to the create trigger after retry", async () => {
    createMock.mockRejectedValueOnce(new Error("新增失敗")).mockResolvedValueOnce(coordinate("new", "第三類"));
    fetchMock.mockResolvedValueOnce(rows).mockResolvedValueOnce([...rows, coordinate("new", "第三類")]);
    render(<CoordinatesTab brandId="brand-one" />);
    const select = await selectCategory();
    const trigger = screen.getByRole("button", { name: "新增座標" });
    trigger.focus();
    fireEvent.click(trigger);
    fireEvent.change(screen.getByRole("textbox", { name: "座標名稱" }), { target: { value: "new coordinate" } });
    fireEvent.change(screen.getByRole("textbox", { name: "分類（選填）" }), { target: { value: "第三類" } });
    fireEvent.submit(screen.getByRole("button", { name: "新增這個座標" }).closest("form")!);
    await screen.findByText("新增失敗");
    expect((screen.getByRole("textbox", { name: "座標名稱" }) as HTMLInputElement).value).toBe("new coordinate");
    expect(select.value).toBe("第二類");
    fireEvent.submit(screen.getByRole("button", { name: "新增這個座標" }).closest("form")!);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await screen.findByRole("option", { name: "第三類（1）" });
    expect((screen.getByRole("combobox", { name: "分類" }) as HTMLSelectElement).value).toBe("第二類");
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });

  it("retains confirmed saved rows and category when reread fails, and retries without clearing the screen", async () => {
    toggleMock.mockResolvedValue({ ...rows[1], disabled_at: "saved" });
    fetchMock.mockResolvedValueOnce(rows).mockRejectedValueOnce(new Error("讀回失敗"))
      .mockResolvedValueOnce(rows.map(row => row.id === "second" ? { ...row, disabled_at: "saved" } : row));
    render(<CoordinatesTab brandId="brand-one" />);
    const select = await selectCategory();
    fireEvent.click(screen.getByRole("checkbox", { name: "啟用" }));
    await screen.findByText("讀回失敗");
    expect(screen.getByRole("checkbox", { name: "已停用" })).toBeTruthy();
    expect(select.value).toBe("第二類");
    fireEvent.click(screen.getByRole("button", { name: "重新載入" }));
    await waitFor(() => expect(screen.queryByText("讀回失敗")).toBeNull());
    expect(select.value).toBe("第二類");
  });

  it("falls back when the selected category disappears, without resurrecting it on the next refresh", async () => {
    toggleMock.mockResolvedValue({ ...rows[1], disabled_at: "saved" });
    fetchMock.mockResolvedValueOnce(rows).mockResolvedValueOnce([rows[0]])
      .mockResolvedValueOnce(rows);
    render(<CoordinatesTab brandId="brand-one" />);
    const select = await selectCategory();
    const removedToggle = screen.getByRole("checkbox", { name: "啟用" });
    removedToggle.focus();
    fireEvent.click(removedToggle);
    await screen.findByText("first coordinate");
    await waitFor(() => expect(document.activeElement).toBe(select));
    expect((screen.getByRole("combobox", { name: "分類" }) as HTMLSelectElement).value).toBe("第一類");
    fireEvent.click(screen.getByRole("checkbox", { name: "啟用" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    await screen.findByRole("option", { name: "第二類（1）" });
    expect((screen.getByRole("combobox", { name: "分類" }) as HTMLSelectElement).value).toBe("第一類");
  });

  it("resets dimension, category and open form when switching brands, and ignores the old request", async () => {
    const oldRefresh = deferred<Coordinate[]>();
    fetchMock.mockResolvedValueOnce(rows).mockReturnValueOnce(oldRefresh.promise)
      .mockResolvedValueOnce([coordinate("other-first", "第一類"), coordinate("other-second", "第二類")]);
    toggleMock.mockResolvedValue({ ...rows[3], disabled_at: "saved" });
    const view = render(<CoordinatesTab brandId="brand-one" />);
    await screen.findByRole("button", { name: /證明/ });
    fireEvent.click(screen.getByRole("button", { name: /證明/ }));
    await selectCategory("證明二");
    fireEvent.click(screen.getByRole("checkbox", { name: "啟用" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    fireEvent.click(screen.getByRole("button", { name: "新增座標" }));
    view.rerender(<CoordinatesTab brandId="brand-two" />);
    await screen.findByText("other-first coordinate");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect((screen.getByRole("combobox", { name: "分類" }) as HTMLSelectElement).value).toBe("第一類");
    await act(async () => oldRefresh.resolve(rows));
    expect(screen.queryByText("proof-second coordinate")).toBeNull();
    expect(screen.getByText("other-first coordinate")).toBeTruthy();
  });

  it("retries the initial load and presents uncategorized coordinates without an invented category", async () => {
    fetchMock.mockRejectedValueOnce(new Error("初次讀取失敗")).mockResolvedValueOnce([coordinate("uncategorized", null)]);
    render(<CoordinatesTab brandId="brand-one" />);
    await screen.findByText("初次讀取失敗");
    fireEvent.click(screen.getByRole("button", { name: "重新載入" }));
    await screen.findByText("uncategorized coordinate");
    expect((screen.getByRole("combobox", { name: "分類" }) as HTMLSelectElement).value).toBe("未分類");
  });
});
