/** frontend/src/components/auth/OrgMenu.test.tsx — 票 03-3 §4：`GET /api/identity/me`
 * 成功後要把 `org.id` 存回 `setOrgId()`，不然單一組織的使用者 `localStorage.orgId`
 * 永遠是 null，每個請求都得靠後端猜預設組織（見 `app/identity/__init__.py`
 * `_resolve_org`）。全程假 `apiFetch`／`@/lib/auth`，不連任何伺服器。 */
import { render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/http", async () => {
  const actual = await vi.importActual<typeof import("@/lib/http")>("@/lib/http");
  return { ...actual, apiFetch: vi.fn() };
});
vi.mock("@/lib/auth", () => ({
  setOrgId: vi.fn(),
  signOut: vi.fn(),
}));

import { setOrgId } from "@/lib/auth";
import { apiFetch } from "@/lib/http";
import { OrgMenu } from "./OrgMenu";

const mockApiFetch = vi.mocked(apiFetch);
const mockSetOrgId = vi.mocked(setOrgId);

afterEach(() => {
  vi.clearAllMocks();
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
});
