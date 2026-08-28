/** 票 03-2 機器閘門第 5、6 項：`apiFetch` 帶 header 的行為與 401 導頁。
 * 全程假 `fetch`、假 `@/lib/auth`，不連任何伺服器。 */
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/auth", () => ({
  getAccessToken: vi.fn(),
  getOrgId: vi.fn(),
  signOut: vi.fn(),
}));

import { getAccessToken, getOrgId, signOut } from "@/lib/auth";
import { _setRedirectForTest, apiFetch } from "@/lib/http";

const mockGetAccessToken = vi.mocked(getAccessToken);
const mockGetOrgId = vi.mocked(getOrgId);
const mockSignOut = vi.mocked(signOut);

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("apiFetch", () => {
  it("有 session 時帶上 Authorization 與 X-Org-Id", async () => {
    mockGetAccessToken.mockResolvedValue("tok123");
    mockGetOrgId.mockReturnValue("org_abc");
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await apiFetch("/api/x");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0];
    const headers = new Headers(init?.headers);
    expect(headers.get("Authorization")).toBe("Bearer tok123");
    expect(headers.get("X-Org-Id")).toBe("org_abc");
  });

  it("沒有 session 時兩個 header 都不帶", async () => {
    mockGetAccessToken.mockResolvedValue(null);
    mockGetOrgId.mockReturnValue(null);
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await apiFetch("/api/x");

    const [, init] = fetchMock.mock.calls[0];
    const headers = new Headers(init?.headers);
    expect(headers.has("Authorization")).toBe(false);
    expect(headers.has("X-Org-Id")).toBe(false);
  });

  it("401 觸發導去登入頁並清掉 session（不把 401 這個 response 交還給呼叫端）", async () => {
    mockGetAccessToken.mockResolvedValue("stale-token");
    mockGetOrgId.mockReturnValue(null);
    mockSignOut.mockResolvedValue(undefined);
    const fetchMock = vi.fn(async () => new Response("{}", { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);
    const redirect = vi.fn();
    _setRedirectForTest(redirect);

    let settled = false;
    void apiFetch("/api/x").then(() => {
      settled = true;
    });

    // 讓 apiFetch 內部一串 await（getAccessToken／getOrgId／fetch／signOut）都跑完——
    // 跨一個 macrotask 保證中間所有 microtask 都清空，但因為 401 分支刻意回傳一個永遠
    // 不 resolve 的 promise，settled 應該一直是 false。
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(mockSignOut).toHaveBeenCalledTimes(1);
    expect(redirect).toHaveBeenCalledWith("/app/login");
    expect(settled).toBe(false);
  });

  it("非 401 的回應原樣交還給呼叫端", async () => {
    mockGetAccessToken.mockResolvedValue(null);
    mockGetOrgId.mockReturnValue(null);
    const fetchMock = vi.fn(async () => new Response('{"ok":true}', { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const res = await apiFetch("/api/x");

    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true });
  });
});
