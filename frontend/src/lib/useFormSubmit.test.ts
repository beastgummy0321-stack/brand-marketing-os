/** F47-I02 (Contract B): the error of `useFormSubmit` clears as soon as the form reports a change. */
import { createElement, useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useFormSubmit } from "./useFormSubmit";

function Form() {
  const [value, setValue] = useState("");
  const form = useFormSubmit(async () => {
    throw new Error("請填一個大於 0 的數字。");
  });
  return createElement(
    "form",
    { ...form.formProps, onSubmit: (e: { preventDefault(): void }) => { e.preventDefault(); void form.submit(); } },
    createElement("input", { "aria-label": "上限", value, onChange: (e: { target: { value: string } }) => setValue(e.target.value) }),
    createElement("button", { type: "button", onClick: form.clearError }, "換模式"),
    createElement("button", { type: "submit" }, "儲存"),
    form.error && createElement("p", { role: "alert" }, form.error),
  );
}

describe("useFormSubmit", () => {
  it("shows the thrown sentence and clears it on the next field change", async () => {
    render(createElement(Form));
    fireEvent.click(screen.getByRole("button", { name: "儲存" }));
    expect((await screen.findByRole("alert")).textContent).toBe("請填一個大於 0 的數字。");
    fireEvent.change(screen.getByLabelText("上限"), { target: { value: "200" } });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("clearError() clears it for a change that is not a form field", async () => {
    render(createElement(Form));
    fireEvent.click(screen.getByRole("button", { name: "儲存" }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "換模式" }));
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

/** F51 Contract S: a save acknowledges — `saved` after a success, cleared by the next change (no timer). */
function SavingForm({ fail = false }: { fail?: boolean }) {
  const [value, setValue] = useState("");
  const form = useFormSubmit(async () => {
    if (fail) throw new Error("儲存失敗");
  });
  return createElement(
    "form",
    { ...form.formProps, onSubmit: (e: { preventDefault(): void }) => { e.preventDefault(); void form.submit(); } },
    createElement("input", { "aria-label": "名稱", value, onChange: (e: { target: { value: string } }) => setValue(e.target.value) }),
    createElement("button", { type: "button", onClick: form.clearError }, "換模式"),
    createElement("button", { type: "submit" }, "儲存"),
    form.saved && createElement("p", { role: "status" }, "已儲存"),
  );
}

describe("useFormSubmit saved", () => {
  it("is set by a successful submit and stays until the form reports a change", async () => {
    render(createElement(SavingForm));
    expect(screen.queryByRole("status")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "儲存" }));
    expect((await screen.findByRole("status")).textContent).toBe("已儲存");
    fireEvent.change(screen.getByLabelText("名稱"), { target: { value: "新名字" } });
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("is cleared by clearError() and never set by a failed submit", async () => {
    const { unmount } = render(createElement(SavingForm));
    fireEvent.click(screen.getByRole("button", { name: "儲存" }));
    await screen.findByRole("status");
    fireEvent.click(screen.getByRole("button", { name: "換模式" }));
    expect(screen.queryByRole("status")).toBeNull();
    unmount();

    render(createElement(SavingForm, { fail: true }));
    fireEvent.click(screen.getByRole("button", { name: "儲存" }));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByRole("status")).toBeNull();
  });
});
