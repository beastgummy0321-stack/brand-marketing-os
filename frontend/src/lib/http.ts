/** frontend/src/lib/http.ts — 全站同源 `/api/...` 呼叫的唯一出口（票 03-2）。
 *
 * `apiFetch` 跟全域 `fetch` 同簽章，呼叫端原本怎麼用 `fetch(path, init)` 就怎麼用
 * `apiFetch(path, init)`，差別只多做三件事：帶 `Authorization`、帶 `X-Org-Id`、401 時
 * 導去登入頁。失敗回應怎麼變成一句話由檔尾的 `throwIfFailed`（F47-I02）負責——全站只有
 * 這一個出口把非 OK 回應轉成 `Error`。
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
/** 記住的路徑放多久算數。邀請連結是「點開、幾分鐘內登入」的即時意圖；同一個分頁隔了
 * 更久之後為了別的事登入，是另一件事，不該被丟回那張沒收完的邀請頁。 */
const PENDING_PATH_TTL_MS = 10 * 60 * 1000;

/** 票 03-3 §3：沒登入的受邀者點開 `/app/accept-invite?token=…`，該頁一掛載就打
 * `apiFetch` 拿 401（沒 token），整頁換成 `/app/login` 之前先把當下路徑（react-router
 * 看得懂的、不含 `/app` 前綴那種）記下來，登入頁成功後撈回去用（見 `App.tsx`
 * `LoginRoute`）。只存一次、讀一次就清掉，不是全站導頁框架。 */
function rememberPendingPath(): void {
  const path = window.location.pathname.replace(/^\/app\/?/, "/") + window.location.search;
  if (path && path !== "/login") {
    sessionStorage.setItem(PENDING_PATH_KEY, JSON.stringify({ path, at: Date.now() }));
  }
}

/** `App.tsx` 的 `LoginRoute` 登入成功後呼叫一次：撈回並清掉上面記住的路徑；沒有、過期、
 * 或存的東西讀不懂（這版之前存的是純字串，跨這次部署的舊分頁就是那種）都回 `null`，
 * 呼叫端自己決定要不要用預設值 `/`。 */
export function takePendingPath(): string | null {
  const raw = sessionStorage.getItem(PENDING_PATH_KEY);
  sessionStorage.removeItem(PENDING_PATH_KEY);
  if (!raw) return null;
  try {
    const { path, at } = JSON.parse(raw) as { path?: unknown; at?: unknown };
    if (typeof path !== "string" || typeof at !== "number") return null;
    return Date.now() - at > PENDING_PATH_TTL_MS ? null : path;
  } catch {
    return null;
  }
}

/** 使用者自己按登出時呼叫（`OrgMenu`）：把記住的路徑丟掉。刻意不塞進 `lib/auth.ts` 的
 * `signOut()`——`apiFetch` 的 401 分支會先記路徑再 `signOut()`，藏在裡面會把剛記的路徑
 * 當場清掉。 */
export function clearPendingPath(): void {
  sessionStorage.removeItem(PENDING_PATH_KEY);
}

const SESSION_EXPIRED_KEY = "sessionExpired";

/** F47-I02: the login page reads this once on mount. `true` only when `apiFetch` just sent the user
 * here because the server answered 401 (the session ran out), so the page can say
 * 「登入已過期，請重新登入」 instead of a bare form. Read-and-clear, like `takePendingPath`. */
export function takeSessionExpired(): boolean {
  const expired = sessionStorage.getItem(SESSION_EXPIRED_KEY) === "1";
  sessionStorage.removeItem(SESSION_EXPIRED_KEY);
  return expired;
}

export async function apiFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const token = await getAccessToken();
  const orgId = getOrgId();

  const headers = new Headers(init?.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (orgId) headers.set("X-Org-Id", orgId);

  const res = await fetch(input, { ...init, headers });

  if (res.status === 401) {
    // F47-I02: remember the page and the "expired" mark BEFORE signing out. `signOut()` fires
    // supabase-js's auth-state broadcast, and `RequireSession` (App.tsx) can re-render into
    // `<Navigate to="/login">` before this await returns — after that `window.location` already
    // reads `/login` and the page the user was on would be lost.
    rememberPendingPath();
    sessionStorage.setItem(SESSION_EXPIRED_KEY, "1");
    await signOut();
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

/** F47-I02 (feature F47 Contract B): the error every shell API client throws for a non-OK response.
 * `message` is the server's own sentence when it sent one; `fieldErrors` carries the per-field
 * messages of the rule-card body (`{"error": "…", "field_errors": {key: "…"}}`) for callers that
 * want to show each message next to its field. */
export class ApiResponseError extends Error {
  readonly status: number;
  readonly fieldErrors: Record<string, string>;
  constructor(message: string, status: number, fieldErrors: Record<string, string> = {}) {
    super(message);
    this.name = "ApiResponseError";
    this.status = status;
    this.fieldErrors = fieldErrors;
  }
}

function fieldErrorsFrom(body: unknown, key: "field_errors" | "errors"): Record<string, string> {
  if (!body || typeof body !== "object") return {};
  const raw = (body as Record<string, unknown>)[key];
  if (!raw || typeof raw !== "object") return {};
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
    if (typeof value === "string" && value) out[key] = value;
  }
  return out;
}

/** F47-I02 (Contract B): the one way a shell API client turns a failed response into an `Error`.
 * Does nothing when `res.ok`; otherwise throws an `ApiResponseError` whose message is, in order:
 * every `errors` field message joined (library writes), the envelope's sentence (`errorMessageFrom`:
 * `{error: "…"}`, `{error: {message}}`, `{detail}`), the first `field_errors` message, or `fallback` (also used for a non-JSON body such as a 502
 * HTML page). A 「…（狀態碼 N）」 text belongs only in `fallback` — `lib/feedbackGuards.test.ts`
 * fails a `lib/*.ts` file that throws one any other way. */
export async function throwIfFailed(res: Response, fallback: string): Promise<void> {
  if (res.ok) return;
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  // Two per-field shapes: the rule-card `field_errors` (its first message stands in when the body has
  // no sentence of its own) and the library writes' `errors` (always shown whole: every field's
  // message joined with 「；」, as `libraryApi.postJson` always did).
  const ruleFields = fieldErrorsFrom(body, "field_errors");
  const libraryFields = fieldErrorsFrom(body, "errors");
  const libraryMessages = Object.values(libraryFields);
  if (libraryMessages.length) throw new ApiResponseError(libraryMessages.join("；"), res.status, libraryFields);
  const message = errorMessageFrom(body, Object.values(ruleFields)[0] ?? fallback);
  throw new ApiResponseError(message, res.status, ruleFields);
}
