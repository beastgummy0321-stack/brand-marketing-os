/** frontend/src/lib/auth.ts — Supabase 登入狀態的唯一出入口（票 03-2）。
 *
 * 為什麼是這支檔案而不是 `03-plan.md` 講的 `src/features/auth/`：這個 repo 沒有
 * `src/features/`——畫面放 `src/components/<feature>/`，資料存取放 `src/lib/*`。跟著
 * repo 現狀走比跟著計畫書的資料夾名字重要；單一檔案也比一整個資料夾更容易被
 * dependency-cruiser 規則盯住「全站只有這支檔案准 import @supabase/supabase-js」——
 * 2026-09-04 這條規則已經接上（`frontend/.dependency-cruiser.cjs`、`npm run depcruise`、
 * CI frontend job），不再只是鋪路（看板 07-1）。同日證紅三種打法都紅：在 `src/lib/` 裡
 * import、在畫面元件裡 import、**只 import 型別**（`import type { Session }`）。第三種
 * 比規則字面更嚴，是刻意留著的：型別也只能從這支檔案借，出入口才真的只有一個。
 *
 * session（access token）的持久化交給 supabase-js 自己（它自己在 localStorage 管
 * 一組 key），這裡不重刻 token 儲存。這支檔案自己存的東西只有一樣：目前選的組織
 * id（key: "orgId"）——`GET /api/identity/me` 回來的 `orgs` 是使用者能切換的組織清單，
 * 選哪一個是前端狀態，不是 supabase-js 管的範圍。
 */
import { createClient, type Session } from "@supabase/supabase-js";
import { useEffect, useState } from "react";

const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_ANON_KEY,
);

const ORG_ID_KEY = "orgId";

/** `lib/http.ts` 組 `X-Org-Id` header 用。沒選過（或剛登出清掉）是 null——後端沒收到
 * 這個 header 時會自己 fallback 回使用者的個人組織（見 app/identity/__init__.py
 * `_resolve_org`），不是前端的錯誤狀態。 */
export function getOrgId(): string | null {
  return localStorage.getItem(ORG_ID_KEY);
}

export function setOrgId(orgId: string | null): void {
  if (orgId) localStorage.setItem(ORG_ID_KEY, orgId);
  else localStorage.removeItem(ORG_ID_KEY);
}

/** `lib/http.ts` 組 `Authorization` header 用。沒有登入回 null。*/
export async function getAccessToken(): Promise<string | null> {
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
}

/** F47-I02: Supabase Auth answers in English (「Invalid login credentials」), and the drill-10 operator
 * saw exactly that on the login page. Map the known causes by `code` (supabase-js ≥ 2.6x sets it),
 * with the English message as a second key for older servers; anything else becomes `fallback`. */
const AUTH_ERRORS: { codes: string[]; messages: RegExp; text: string }[] = [
  { codes: ["invalid_credentials"], messages: /invalid login credentials/i, text: "帳號或密碼不對" },
  {
    codes: ["email_not_confirmed"],
    messages: /email not confirmed/i,
    text: "這個信箱還沒完成驗證：請先到信箱點確認連結，再回來登入。",
  },
  {
    codes: ["over_request_rate_limit", "over_email_send_rate_limit", "over_sms_send_rate_limit"],
    messages: /rate limit|too many requests/i,
    text: "嘗試太多次了，請等幾分鐘再試。",
  },
  {
    codes: ["user_already_exists", "email_exists"],
    messages: /already registered|already exists/i,
    text: "這個帳號已經註冊過了，請改用登入。",
  },
  { codes: ["weak_password"], messages: /password should be/i, text: "密碼太簡單或太短，請換一組至少 6 個字元的密碼。" },
];

export function authErrorMessage(
  error: { code?: string; message?: string; status?: number } | null,
  fallback = "登入失敗，請稍後再試",
): string | null {
  if (!error) return null;
  const known = AUTH_ERRORS.find(
    (e) => (error.code && e.codes.includes(error.code)) || (error.message && e.messages.test(error.message)),
  );
  if (known) return known.text;
  if (error.status === 429) return "嘗試太多次了，請等幾分鐘再試。";
  return fallback;
}

/** 三種登入方式都回傳「錯誤訊息或 null」，畫面自己決定怎麼顯示——不在這裡丟例外。
 * 訊息一律經 `authErrorMessage` 換成中文（F47-I02）。 */
export async function signInWithPassword(email: string, password: string): Promise<string | null> {
  const { error } = await supabase.auth.signInWithPassword({ email, password });
  return authErrorMessage(error);
}

export async function signUpWithPassword(email: string, password: string): Promise<string | null> {
  const { error } = await supabase.auth.signUp({ email, password });
  return authErrorMessage(error, "註冊失敗，請稍後再試");
}

export async function signInWithMagicLink(email: string): Promise<string | null> {
  const { error } = await supabase.auth.signInWithOtp({ email });
  return authErrorMessage(error, "登入連結寄送失敗，請稍後再試");
}

/** 登出：連組織選擇一起清掉，不然下次不同帳號登入會先帶著上一個帳號選的 org id
 * 打 `X-Org-Id`，後端會用「不在這個組織」403 擋下來（見 `_resolve_org`），畫面上看起來
 * 像是登入壞了，其實是殘留狀態。`lib/http.ts` 的 401 攔截器也呼叫這支，同一份邏輯。 */
export async function signOut(): Promise<void> {
  setOrgId(null);
  await supabase.auth.signOut();
}

/** App.tsx 路由守門與 LoginPage 用：讀「現在有沒有登入」，不是直接戳 localStorage。
 * 掛載時先問一次 `getSession()`（讀本機快取，不一定打網路），之後交給 supabase-js 的
 * `onAuthStateChange` 廣播接手更新——登入、登出、分頁間 token 刷新都會經過這裡，呼叫端
 * 不用自己 poll。*/
export function useSession(): { loading: boolean; session: Session | null } {
  const [state, setState] = useState<{ loading: boolean; session: Session | null }>({
    loading: true,
    session: null,
  });

  useEffect(() => {
    let cancelled = false;
    supabase.auth.getSession().then(({ data }) => {
      if (!cancelled) setState({ loading: false, session: data.session });
    });
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      if (!cancelled) setState({ loading: false, session });
    });
    return () => {
      cancelled = true;
      subscription.unsubscribe();
    };
  }, []);

  return state;
}
