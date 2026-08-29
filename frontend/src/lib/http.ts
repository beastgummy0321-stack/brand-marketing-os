/** frontend/src/lib/http.ts — 全站同源 `/api/...` 呼叫的唯一出口（票 03-2）。
 *
 * `apiFetch` 跟全域 `fetch` 同簽章，呼叫端原本怎麼用 `fetch(path, init)` 就怎麼用
 * `apiFetch(path, init)`，差別只多做三件事：帶 `Authorization`、帶 `X-Org-Id`、401 時
 * 導去登入頁。其餘（response 怎麼判斷成功、怎麼解析 body、丟什麼錯誤訊息）維持呼叫端
 * 自己的寫法不動——這支檔案不猜每個呼叫端想要什麼樣的錯誤處理。
 *
 * 刻意不 monkey-patch 全域 `fetch`：`lib/auth.ts` 用的 supabase-js 用戶端函式庫也用同一個
 * 全域 `fetch` 跟 Supabase Auth 伺服器講話，那些請求不該被硬塞 `X-Org-Id`，401 也不該
 * 觸發這裡的導頁邏輯（那是 supabase-js 自己的登入流程，不是「登入過期」）。
 */
import { getAccessToken, getOrgId, setOrgId, signOut } from "@/lib/auth";

/** 401 時要去哪裡：預設真的改網址列（`window.location`），測試會換成假的 stub 斷言
 * 「有沒有被呼叫、呼叫了什麼路徑」，不用真的觸發瀏覽器導頁。basename 是 `/app`
 * （main.tsx `<BrowserRouter basename="/app">`），這裡不是 react-router 的 navigate，
 * 是整頁改網址，所以要自己補上 `/app` 前綴。 */
let redirectToLogin: (path: string) => void = (path) => {
  window.location.href = path;
};

/** 測試專用：換掉 401 導頁的實作。正式程式碼不會呼叫這支。 */
export function _setRedirectForTest(fn: (path: string) => void): void {
  redirectToLogin = fn;
}

const PENDING_PATH_KEY = "pendingPath";

/** 票 03-3 §3：沒登入的受邀者點開 `/app/accept-invite?token=…`，該頁一掛載就打
 * `apiFetch` 拿 401（沒 token），整頁換成 `/app/login` 之前先把當下路徑（react-router
 * 看得懂的、不含 `/app` 前綴那種）記下來，登入頁成功後撈回去用（見 `App.tsx`
 * `LoginRoute`）。只存一次、讀一次就清掉，不是全站導頁框架。 */
function rememberPendingPath(): void {
  const path = window.location.pathname.replace(/^\/app\/?/, "/") + window.location.search;
  if (path && path !== "/login") {
    sessionStorage.setItem(PENDING_PATH_KEY, path);
  }
}

/** `App.tsx` 的 `LoginRoute` 登入成功後呼叫一次：撈回並清掉上面記住的路徑；沒有就回
 * `null`，呼叫端自己決定要不要用預設值 `/`。 */
export function takePendingPath(): string | null {
  const path = sessionStorage.getItem(PENDING_PATH_KEY);
  sessionStorage.removeItem(PENDING_PATH_KEY);
  return path;
}

export async function apiFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const token = await getAccessToken();
  const orgId = getOrgId();

  const headers = new Headers(init?.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (orgId) headers.set("X-Org-Id", orgId);

  const res = await fetch(input, { ...init, headers });

  if (res.status === 401) {
    await signOut();
    rememberPendingPath();
    redirectToLogin("/app/login");
    // 導頁已經觸發：不把 401 這個 Response 交還給呼叫端，呼叫端多半是
    // `if (!res.ok) throw new Error(...)` 這種寫法，會在畫面短暫閃出一句「讀取失敗」
    // 才被導走。整頁導頁本來就會讓這支 promise 的呼叫端跟著卸載，永遠不 resolve
    // 沒有任何副作用（不像丟例外那樣還會被呼叫端的 catch 接住渲染出嚇人的訊息）。
    return new Promise<Response>(() => {});
  }

  // 2026-08-29：`localStorage.orgId` 記著一個「這個帳號已經不屬於」的組織時，後端每一支
  // API 都回 403 `forbidden_org`，畫面上是一句「設定讀取失敗（狀態碼 403）」——全站模組
  // 同時死掉，而且訊息完全沒說是哪裡出問題。實際踩到的情境：同一台瀏覽器先後登入過不同
  // 帳號（或跑過註冊 smoke），舊的 orgId 還留著。
  //
  // 記住的組織過期不該把整個站鎖死：把它清掉、不帶 header 重打一次就好——後端在沒有
  // `X-Org-Id` 時本來就會退回這個使用者最早的成員資格（app/identity/__init__.py
  // `_resolve_org`），那正是這裡要的結果。只在「真的送過 orgId」且錯誤碼真的是
  // `forbidden_org` 時才重試：其他 403（例如非 owner 動 owner 的東西）照樣原樣交還，
  // 不然會把「你沒有權限」偽裝成「再試一次」。
  if (res.status === 403 && orgId) {
    const code = await res
      .clone()
      .json()
      .then((body) => body?.error?.code)
      .catch(() => null);
    if (code === "forbidden_org") {
      setOrgId(null);
      const retryHeaders = new Headers(init?.headers);
      if (token) retryHeaders.set("Authorization", `Bearer ${token}`);
      return fetch(input, { ...init, headers: retryHeaders });
    }
  }

  return res;
}

/** 後端有兩種錯誤外殼，這支兩種都吃得下：
 *  - `{"error": "請填寫品牌名稱。"}`——`app/main.py` 的 `_error()` 與各路由的手寫回應
 *  - `{"error": {"code": …, "message": "請先登入", "details": …}}`——`web.ApiError` 的
 *    exception handler（`app/main.py:506`）
 *
 * 2026-08-29 修：五個 api 檔各自只認得其中一種。認字串的那幾支（intake／library／
 * products）碰到物件外殼時，`new Error(物件)` 會變成畫面上的 **`[object Object]`**——
 * 建檔精靈第一步上傳產品照踩到的就是這個：真正的原因是 401「請先登入」，但使用者看到
 * 一句沒有意義的話，不知道自己該重新登入。認物件的那幾支（meta／schedule）反過來會把
 * 字串外殼吃掉、只顯示 fallback。
 *
 * 兩種外殼誰對不在這裡處理——畫面的職責是把後端真的回了什麼講給人聽。 */
export function errorMessageFrom(body: unknown, fallback: string): string {
  if (!body || typeof body !== "object") return fallback;
  const err = (body as { error?: unknown }).error;
  if (typeof err === "string" && err) return err;
  if (err && typeof err === "object") {
    const message = (err as { message?: unknown }).message;
    if (typeof message === "string" && message) return message;
  }
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "string" && detail) return detail;
  return fallback;
}

/** `errorMessageFrom` 的 Response 版：讀不出 JSON（例如 502 回了 HTML）就用 fallback。 */
export async function errorMessageFromResponse(res: Response, fallback: string): Promise<string> {
  try {
    return errorMessageFrom(await res.json(), fallback);
  } catch {
    return fallback;
  }
}
