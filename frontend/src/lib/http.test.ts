/** 票 03-2 機器閘門第 5、6 項：`apiFetch` 帶 header 的行為與 401 導頁。
 * 全程假 `fetch`、假 `@/lib/auth`，不連任何伺服器。 */
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/auth", () => ({
  getAccessToken: vi.fn(),
  getOrgId: vi.fn(),
  setOrgId: vi.fn(),
  signOut: vi.fn(),
}));

import { getAccessToken, getOrgId, setOrgId, signOut } from "@/lib/auth";
import {
  _setRedirectForTest,
  ApiResponseError,
  apiFetch,
  errorMessageFrom,
  takePendingPath,
  takeSessionExpired,
  throwIfFailed,
} from "@/lib/http";

const mockGetAccessToken = vi.mocked(getAccessToken);
const mockGetOrgId = vi.mocked(getOrgId);
const mockSetOrgId = vi.mocked(setOrgId);
const mockSignOut = vi.mocked(signOut);

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  sessionStorage.clear();
  window.history.pushState({}, "", "/");
});

describe("apiFetch", () => {
  it("403 forbidden_org：清掉記住的組織、不帶 X-Org-Id 重打一次", async () => {
    mockGetAccessToken.mockResolvedValue("tok123");
    mockGetOrgId.mockReturnValue("org_stale");
    const fetchMock = vi
      .fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response("{}", { status: 200 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ error: { code: "forbidden_org", message: "你不在這個組織裡" } }), {
          status: 403,
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const res = await apiFetch("/api/settings");

    expect(res.status).toBe(200);
    expect(mockSetOrgId).toHaveBeenCalledWith(null);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).get("X-Org-Id")).toBe("org_stale");
    expect(new Headers(fetchMock.mock.calls[1][1]?.headers).get("X-Org-Id")).toBeNull();
  });

  it("其他 403 原樣交還，不清組織也不重試", async () => {
    mockGetAccessToken.mockResolvedValue("tok123");
    mockGetOrgId.mockReturnValue("org_abc");
    const fetchMock = vi.fn(
      async (_input: RequestInfo | URL, _init?: RequestInit) =>
        new Response(JSON.stringify({ error: { code: "forbidden_role", message: "只有負責人可以改" } }), {
          status: 403,
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const res = await apiFetch("/api/settings");

    expect(res.status).toBe(403);
    expect(mockSetOrgId).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

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

  it("票 03-3 §3：401 時記住當下路徑（去掉 /app 前綴），登入頁可以撈回來一次就清掉", async () => {
    mockGetAccessToken.mockResolvedValue(null);
    mockGetOrgId.mockReturnValue(null);
    mockSignOut.mockResolvedValue(undefined);
    const fetchMock = vi.fn(async () => new Response("{}", { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);
    _setRedirectForTest(vi.fn());
    window.history.pushState({}, "", "/app/accept-invite?token=abc123");

    void apiFetch("/api/identity/invites/abc123/accept", { method: "POST" });
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(takePendingPath()).toBe("/accept-invite?token=abc123");
    expect(takePendingPath()).toBeNull(); // 撈第二次應該是空的——只消費一次
  });

  /** F47-I02: `signOut()` broadcasts the auth change and `RequireSession` can navigate to `/login`
   * before it returns. The page the user was on must already be remembered by then, and the login
   * page must learn the session expired. */
  it("401 remembers the page and the expired mark before signOut can move the URL to /login", async () => {
    mockGetAccessToken.mockResolvedValue("stale-token");
    mockGetOrgId.mockReturnValue(null);
    mockSignOut.mockImplementation(async () => {
      window.history.pushState({}, "", "/app/login");
    });
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 401 })));
    _setRedirectForTest(vi.fn());
    window.history.pushState({}, "", "/app/brands/b1/ads?tab=assets");

    void apiFetch("/api/x");
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(takePendingPath()).toBe("/brands/b1/ads?tab=assets");
    expect(takeSessionExpired()).toBe(true);
    expect(takeSessionExpired()).toBe(false); // read once
  });

  /** 記住的路徑只代表「剛剛點開邀請連結」那個當下的意圖。同一個分頁隔了很久之後為了
   * 別的事登入，還被丟回別人的邀請頁，是把一個帳號的入口交給另一次登入。過期的、以及
   * 這版之前存的純字串（跨部署的舊分頁），一律當成沒有並清掉。 */
  it("過期或讀不懂的 pendingPath 一律當成沒有，並且清掉", () => {
    sessionStorage.setItem(
      "pendingPath",
      JSON.stringify({ path: "/accept-invite?token=abc123", at: Date.now() - 11 * 60 * 1000 }),
    );
    expect(takePendingPath()).toBeNull();
    expect(sessionStorage.getItem("pendingPath")).toBeNull();

    sessionStorage.setItem("pendingPath", "/accept-invite?token=abc123"); // 舊格式：純字串
    expect(takePendingPath()).toBeNull();
    expect(sessionStorage.getItem("pendingPath")).toBeNull();
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

describe("errorMessageFrom", () => {
  /** 2026-08-29：建檔精靈第一步上傳產品照，畫面顯示 `[object Object]`。真正的原因是 401
   * 「請先登入」，但後端的 `ApiError` 外殼是物件（`{error:{code,message,details}}`），而這
   * 幾支 api 檔只認得字串外殼（`{error:"…"}`），`new Error(物件)` 就變成那句沒有意義的話。
   * 兩種外殼都要讀得出來，讀不出來時退回可讀的預設句，永遠不要把物件丟給 `new Error`。 */
  it("讀得出物件外殼的 message（就是那個 [object Object] 的成因）", () => {
    const body = { error: { code: "unauthenticated", message: "請先登入", details: null } };
    expect(errorMessageFrom(body, "預設")).toBe("請先登入");
  });

  it("讀得出字串外殼", () => {
    expect(errorMessageFrom({ error: "請填寫品牌名稱。" }, "預設")).toBe("請填寫品牌名稱。");
  });

  it("讀得出 FastAPI 的 detail", () => {
    expect(errorMessageFrom({ detail: "Not Found" }, "預設")).toBe("Not Found");
  });

  it("認不得的形狀一律退回預設句，不吐出 [object Object]", () => {
    for (const body of [null, undefined, "字串", 42, {}, { error: {} }, { error: { code: "x" } }]) {
      const message = errorMessageFrom(body, "預設");
      expect(message).toBe("預設");
      expect(message).not.toContain("[object");
    }
  });
});

describe("throwIfFailed (F47-I02, Contract B)", () => {
  const FALLBACK = "儲存失敗（狀態碼 400）";
  const json = (body: unknown, status = 400) =>
    new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

  async function messageOf(res: Response): Promise<ApiResponseError> {
    try {
      await throwIfFailed(res, FALLBACK);
    } catch (err) {
      return err as ApiResponseError;
    }
    throw new Error("expected throwIfFailed to throw");
  }

  it("does nothing for an OK response", async () => {
    await expect(throwIfFailed(new Response("{}", { status: 200 }), FALLBACK)).resolves.toBeUndefined();
  });

  it("reads {error: string}", async () => {
    const err = await messageOf(json({ error: "AI 月費上限請填大於 0 的數字，例如 200。" }));
    expect(err).toBeInstanceOf(ApiResponseError);
    expect(err.message).toBe("AI 月費上限請填大於 0 的數字，例如 200。");
    expect(err.status).toBe(400);
  });

  it("reads {error: {message}}", async () => {
    expect((await messageOf(json({ error: { code: "x", message: "請先登入" } }, 403))).message).toBe("請先登入");
  });

  it("reads {detail}", async () => {
    expect((await messageOf(json({ detail: "找不到這個品牌" }, 404))).message).toBe("找不到這個品牌");
  });

  it("reads the rule-card field_errors body: the sentence, plus each field for callers that map them", async () => {
    const err = await messageOf(
      json({ error: "有欄位沒有填一個大於 0 的數字。", field_errors: { plan_count_min: "請填一個大於 0 的數字。" } }),
    );
    expect(err.message).toBe("有欄位沒有填一個大於 0 的數字。");
    expect(err.fieldErrors).toEqual({ plan_count_min: "請填一個大於 0 的數字。" });
    const bare = await messageOf(json({ field_errors: { a: "第一個欄位不對。", b: "第二個欄位不對。" } }));
    expect(bare.message).toBe("第一個欄位不對。");
  });

  it("reads the library {errors} dict: every field's message joined", async () => {
    const err = await messageOf(json({ errors: { name: "請填名稱。", url: "網址格式不對。" } }));
    expect(err.message).toBe("請填名稱。；網址格式不對。");
  });

  it("non-JSON or unknown body falls back to the caller's sentence", async () => {
    expect((await messageOf(new Response("<html>502</html>", { status: 502 }))).message).toBe(FALLBACK);
    expect((await messageOf(json({ ok: false }, 500))).message).toBe(FALLBACK);
  });
});
