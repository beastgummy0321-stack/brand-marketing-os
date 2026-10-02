/** F47-I02: the login page speaks Chinese, clears its error when the mode or a field changes, says
 * when a session expired. (Returning to the remembered page after sign-in is `App.tsx` `LoginRoute` +
 * `takePendingPath`; the 401 side of it — remembering before `signOut()` can move the URL — is
 * covered in `lib/http.test.ts`. Tests may not import `App.tsx`: depcruise `only-main-imports-the-app-shell`.) */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

const session = { current: null as null | { user: { id: string } } };

vi.mock("@/lib/auth", async () => {
  const actual = await vi.importActual<typeof import("@/lib/auth")>("@/lib/auth");
  return {
    ...actual,
    signInWithPassword: vi.fn(),
    signUpWithPassword: vi.fn(),
    signInWithMagicLink: vi.fn(),
    useSession: () => ({ loading: false, session: session.current }),
  };
});

import { authErrorMessage, signInWithPassword } from "@/lib/auth";
import { LoginPage } from "./LoginPage";

const mockSignIn = vi.mocked(signInWithPassword);

afterEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  session.current = null;
});

describe("authErrorMessage", () => {
  it("maps Supabase's English errors to Chinese", () => {
    expect(authErrorMessage({ code: "invalid_credentials", message: "Invalid login credentials" })).toBe("帳號或密碼不對");
    expect(authErrorMessage({ message: "Invalid login credentials" })).toBe("帳號或密碼不對");
    expect(authErrorMessage({ code: "email_not_confirmed", message: "Email not confirmed" })).toContain("還沒完成驗證");
    expect(authErrorMessage({ code: "over_request_rate_limit", message: "x", status: 429 })).toContain("嘗試太多次");
    expect(authErrorMessage({ message: "Request rate limit reached", status: 429 })).toContain("嘗試太多次");
    expect(authErrorMessage({ code: "unexpected_failure", message: "Database error" })).toBe("登入失敗，請稍後再試");
    expect(authErrorMessage(null)).toBeNull();
  });
});

describe("LoginPage", () => {
  it("shows the Chinese error and drops it when the mode switches or a field changes", async () => {
    mockSignIn.mockResolvedValue("帳號或密碼不對");
    const user = userEvent.setup();
    render(<MemoryRouter><LoginPage /></MemoryRouter>);

    await user.type(screen.getByLabelText("Email"), "123@example.com");
    await user.type(screen.getByLabelText("密碼"), "wrong");
    await user.click(screen.getByRole("button", { name: "登入", exact: true } as never));
    expect((await screen.findByRole("alert")).textContent).toBe("帳號或密碼不對");

    await user.type(screen.getByLabelText("密碼"), "1");
    expect(screen.queryByRole("alert")).toBeNull();

    await user.click(screen.getByRole("button", { name: "登入", exact: true } as never));
    await screen.findByRole("alert");
    await user.click(screen.getByRole("button", { name: "還沒有帳號？註冊新帳號" }));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("says the session expired after a 401 redirect, once", () => {
    sessionStorage.setItem("sessionExpired", "1");
    const { unmount } = render(<MemoryRouter><LoginPage /></MemoryRouter>);
    expect(screen.getByText("登入已過期，請重新登入")).toBeTruthy();
    unmount();
    render(<MemoryRouter><LoginPage /></MemoryRouter>);
    expect(screen.queryByText("登入已過期，請重新登入")).toBeNull();
  });
});
