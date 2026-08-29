import { useState } from "react";
import { signInWithMagicLink, signInWithPassword, signUpWithPassword } from "@/lib/auth";
import { useFormSubmit } from "@/lib/useFormSubmit";

type Mode = "signin" | "signup" | "magiclink";

/** 登入頁（票 03-2）：Email＋密碼（登入／註冊）＋ magic link 三選一，全部走 Supabase
 * 預設流程（票面「Supabase 預設流程即可，本票不做自訂密碼規則、不做自訂信件模板」）。
 * 路由 `/login`（`App.tsx`，basename `/app` 所以實際網址是 `/app/login`）。 */
export function LoginPage() {
  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [magicLinkSent, setMagicLinkSent] = useState(false);

  const form = useFormSubmit(async () => {
    setMagicLinkSent(false);
    let errorMessage: string | null;
    if (mode === "signin") {
      errorMessage = await signInWithPassword(email, password);
    } else if (mode === "signup") {
      errorMessage = await signUpWithPassword(email, password);
    } else {
      errorMessage = await signInWithMagicLink(email);
      if (!errorMessage) setMagicLinkSent(true);
    }
    if (errorMessage) throw new Error(errorMessage);
    // 成功後不用自己導頁：`App.tsx` 的 `useSession()` 會收到 supabase-js 的
    // `onAuthStateChange` 廣播，`/login` 那條路由看到 session 存在自動轉去首頁。
  });

  return (
    <div className="flex h-full items-center justify-center bg-background">
      <div className="w-full max-w-sm rounded-[var(--radius-xl)] border border-border bg-card p-8 shadow-[var(--shadow-card)]">
        <h1 className="font-display text-2xl text-foreground">行銷駕駛艙</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {mode === "signup" ? "註冊新帳號" : mode === "magiclink" ? "用郵件連結登入" : "登入"}
        </p>

        <form
          className="mt-6 flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            void form.submit();
          }}
        >
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-foreground">Email</span>
            {/* 內部測試用：帳號改成不是信箱格式的短字串（例如 123），type="email" 會被
                瀏覽器自己擋在送出之前。Supabase Auth 本身收非信箱的帳號，擋人的是這一行。
                正式發布前改回 type="email"。 */}
            <input
              type="text"
              required
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
            />
          </label>

          {mode !== "magiclink" && (
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium text-foreground">密碼</span>
              <input
                type="password"
                required
                autoComplete={mode === "signup" ? "new-password" : "current-password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
              />
            </label>
          )}

          {form.error && <p className="text-sm text-danger">{form.error}</p>}
          {magicLinkSent && (
            <p className="text-sm text-success">連結已經寄出，去信箱收信點連結登入。</p>
          )}

          <button
            type="submit"
            disabled={form.saving}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {form.saving
              ? "處理中…"
              : mode === "signup"
                ? "註冊"
                : mode === "magiclink"
                  ? "寄送登入連結"
                  : "登入"}
          </button>
        </form>

        <div className="mt-4 flex flex-col gap-1 text-sm text-muted-foreground">
          {mode !== "signin" && (
            <button type="button" onClick={() => setMode("signin")} className="text-left text-primary hover:underline">
              改用 Email／密碼登入
            </button>
          )}
          {mode !== "signup" && (
            <button type="button" onClick={() => setMode("signup")} className="text-left text-primary hover:underline">
              還沒有帳號？註冊新帳號
            </button>
          )}
          {mode !== "magiclink" && (
            <button type="button" onClick={() => setMode("magiclink")} className="text-left text-primary hover:underline">
              改用郵件連結登入（不用密碼）
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
