import { useEffect, useState } from "react";
import { Logo } from "@/components/layout/Logo";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import {
  signInWithMagicLink,
  signInWithPassword,
  signUpWithPassword,
} from "@/lib/auth";
import { takeSessionExpired } from "@/lib/http";
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
  // F47-I02／F51 Contract H: `lib/http.ts` marks an expired session (and a write it did not send);
  // read-and-clear once in an effect (StrictMode runs it twice in dev, and the second read is already
  // empty — so only ever set it here, never clear it from the read).
  const [expired, setExpired] = useState<null | { actionLost: boolean }>(null);
  useEffect(() => {
    const mark = takeSessionExpired();
    if (mark.expired) setExpired({ actionLost: mark.actionLost });
  }, []);

  const form = useFormSubmit(async () => {
    setMagicLinkSent(false);
    setExpired(null);
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

  /** The error belongs to the mode it was raised in (drill-10: a wrong-password sentence stayed after
   * switching to 註冊). */
  function switchMode(next: Mode) {
    setMode(next);
    setMagicLinkSent(false);
    form.clearError();
  }

  return (
    <div className="auth-layout">
      <aside className="auth-aside">
        <Logo />
        <div className="max-w-lg">
          <p className="mb-6 text-sm font-medium text-primary">
            品牌經營，從掌握全貌開始。
          </p>
          <h2 className="text-4xl font-semibold leading-snug tracking-tight">
            每個品牌的下一步，
            <br />
            都在同一個工作區。
          </h2>
          <p className="mt-6 max-w-sm leading-7 text-muted-foreground">
            整合廣告成效、產品知識與投放中心，讓經營判斷有資料可以依據。
          </p>
          <div className="mt-10 flex flex-wrap gap-3 text-xs text-primary">
            <span className="rounded-lg border border-primary/15 px-4 py-3">
              品牌工作區
            </span>
            <span className="rounded-lg border border-primary/15 px-4 py-3">
              廣告成效看板
            </span>
            <span className="rounded-lg border border-primary/15 px-4 py-3">
              團隊協作
            </span>
          </div>
        </div>
        <p className="text-xs text-muted-foreground">
          行銷駕駛艙 · Brand workspace
        </p>
      </aside>
      <main className="flex items-center justify-center p-12">
        <div className="w-full max-w-sm">
          <h1 className="text-3xl font-semibold">
            {mode === "signup" ? "建立你的工作區" : "歡迎回來"}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {mode === "signup"
              ? "註冊新帳號"
              : mode === "magiclink"
                ? "用郵件連結登入"
                : "登入"}
          </p>

          {expired && (
            <p role="status" className="mt-4 rounded-md bg-warning/10 px-3 py-2 text-sm text-warning">
              登入已過期，請重新登入
              {expired.actionLost && "。剛才按的那一下沒有送出，沒有資料被改；回到原頁後請再按一次。"}
            </p>
          )}

          <form
            className="mt-6 flex flex-col gap-4"
            {...form.formProps}
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
              <Input
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
                <Input
                  type="password"
                  required
                  autoComplete={
                    mode === "signup" ? "new-password" : "current-password"
                  }
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
                />
              </label>
            )}

            {form.error && <p role="alert" className="text-sm text-danger">{form.error}</p>}
            {magicLinkSent && (
              <p className="text-sm text-success">
                連結已經寄出，去信箱收信點連結登入。
              </p>
            )}

            <Button
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
            </Button>
          </form>

          <div className="mt-4 flex flex-col gap-1 text-sm text-muted-foreground">
            {mode !== "signin" && (
              <Button
                variant="link"
                type="button"
                onClick={() => switchMode("signin")}
                className="text-left text-primary hover:underline"
              >
                改用 Email／密碼登入
              </Button>
            )}
            {mode !== "signup" && (
              <Button
                variant="link"
                type="button"
                onClick={() => switchMode("signup")}
                className="text-left text-primary hover:underline"
              >
                還沒有帳號？註冊新帳號
              </Button>
            )}
            {mode !== "magiclink" && (
              <Button
                variant="link"
                type="button"
                onClick={() => switchMode("magiclink")}
                className="text-left text-primary hover:underline"
              >
                改用郵件連結登入（不用密碼）
              </Button>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
