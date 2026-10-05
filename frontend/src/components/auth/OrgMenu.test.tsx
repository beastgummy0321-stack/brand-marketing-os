/** frontend/src/components/auth/OrgMenu.test.tsx — 票 03-3 §4：`GET /api/identity/me`
 * 成功後要把 `org.id` 存回 `setOrgId()`，不然單一組織的使用者 `localStorage.orgId`
 * 永遠是 null，每個請求都得靠後端猜預設組織（見 `app/identity/__init__.py`
 * `_resolve_org`）。全程假 `apiFetch`／`@/lib/auth`，不連任何伺服器。 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/http", async () => {
  const actual = await vi.importActual<typeof import("@/lib/http")>("@/lib/http");
  return { ...actual, apiFetch: vi.fn() };
});
vi.mock("@/lib/auth", () => ({
  setOrgId: vi.fn(),
  signOut: vi.fn(),
}));

import { setOrgId, signOut } from "@/lib/auth";
import { apiFetch, leaveForLogin, takePendingPath, takeSessionExpired } from "@/lib/http";
import { OrgMenu } from "./OrgMenu";

const mockApiFetch = vi.mocked(apiFetch);
const mockSetOrgId = vi.mocked(setOrgId);
const mockSignOut = vi.mocked(signOut);

const ORG = { id: "org_abc", name: "我的組織", kind: "personal", role: "owner" };
const ME = { user: { id: "u1", email: "a@example.com" }, org: ORG, orgs: [ORG] };

afterEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
});

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
}

describe("OrgMenu", () => {
  it("GET /api/identity/me 成功後把 org.id 存回 setOrgId()", async () => {
    mockApiFetch.mockImplementation(async (input) => {
      if (String(input) === "/api/identity/me") {
        return jsonResponse({
          user: { id: "u1", email: "a@example.com" },
          org: { id: "org_abc", name: "我的組織", kind: "personal", role: "owner" },
          orgs: [{ id: "org_abc", name: "我的組織", kind: "personal", role: "owner" }],
        });
      }
      throw new Error(`unexpected apiFetch call: ${String(input)}`);
    });

    render(<OrgMenu />);

    await waitFor(() => expect(mockSetOrgId).toHaveBeenCalledWith("org_abc"));
  });

  /** F51 Contract H: 登出 is the user's own choice — the login page must not say the session expired
   * nor send the next sign-in back to the page the user left. */
  it("登出 forgets the remembered page and leaves no expired mark", async () => {
    window.history.pushState({}, "", "/app/brands/b1");
    leaveForLogin("expired", { write: true }); // a stale mark from an earlier expiry
    const user = userEvent.setup();
    render(<OrgMenu identity={ME} />);

    await user.click(screen.getByRole("button", { name: "登出" }));

    await waitFor(() => expect(mockSignOut).toHaveBeenCalledTimes(1));
    expect(takeSessionExpired()).toEqual({ expired: false, actionLost: false });
    expect(takePendingPath()).toBeNull();
    window.history.pushState({}, "", "/");
  });

  it("a failed identity read says why instead of rendering nothing", async () => {
    mockApiFetch.mockResolvedValue(
      new Response(JSON.stringify({ error: { code: "internal", message: "工作區暫時讀不到，請重新載入。" } }), { status: 500 }),
    );

    render(<OrgMenu />);

    expect((await screen.findByRole("alert")).textContent).toBe("工作區暫時讀不到，請重新載入。");
  });
});
