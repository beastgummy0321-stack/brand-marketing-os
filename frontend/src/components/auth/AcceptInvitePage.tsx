import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Logo } from "@/components/layout/Logo";
import { apiFetch, readJson } from "@/lib/http";
import { setOrgId } from "@/lib/auth";

interface AcceptInviteResponse {
  org: { id: string; name: string; kind: string; role: string };
}

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "done"; orgName: string };

/** 接受邀請頁（票 03-2）：路由 `/accept-invite?token=…`（`App.tsx`）。刻意不掛在
 * `App.tsx` 的登入守門之下——沒登入時 `apiFetch` 打 401，`lib/http.ts` 的攔截器自己會
 * 導去 `/login`，這裡不用重複判斷「有沒有登入」。錯誤文字直接用後端回的那一句
 * （票面「不要自己發明新的措辭」）——F51 Contract H：信封怎麼讀是 `lib/http.ts` 的事，
 * `{error: "…"}` 與 `{error: {message}}` 都讀得出來；斷線也由它說成一句話。 */
export function AcceptInvitePage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    if (!token) {
      setState({
        status: "error",
        message: "這個邀請連結少了 token，請跟邀請你的人要一份新的連結。",
      });
      return;
    }
    let cancelled = false;
    apiFetch(`/api/identity/invites/${encodeURIComponent(token)}/accept`, {
      method: "POST",
    })
      .then((res) => readJson<AcceptInviteResponse>(res, `加入失敗（狀態碼 ${res.status}）`))
      .then((body) => {
        if (cancelled) return;
        // 接受邀請的人要落在剛加入的那個組織，不是自己的個人組織——不設這一行的話
        // 後端預設組織會挑「最早加入的」（個人組織），點邀請連結等於白點。
        setOrgId(body.org.id);
        setState({ status: "done", orgName: body.org.name });
      })
      .catch((err: unknown) => {
        if (!cancelled)
          setState({ status: "error", message: err instanceof Error && err.message ? err.message : "加入失敗，請稍後再試。" });
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  return (
    <div className="flex min-h-dvh items-center justify-center bg-background p-8">
      <div className="w-full max-w-sm rounded-[var(--radius-xl)] border border-border bg-card p-8 text-center shadow-[var(--shadow-card)]">
        <div className="mb-8 flex justify-center">
          <Logo />
        </div>
        <h1 className="mb-5 text-2xl">加入品牌工作區</h1>
        {state.status === "loading" && (
          <p className="text-sm text-muted-foreground">處理邀請中…</p>
        )}
        {state.status === "error" && (
          <>
            <p className="text-sm text-danger">{state.message}</p>
            <Link
              to="/"
              className="mt-4 inline-block text-sm text-primary hover:underline"
            >
              回到首頁
            </Link>
          </>
        )}
        {state.status === "done" && (
          <>
            <p className="text-sm text-foreground">
              已經加入「{state.orgName}」。
            </p>
            <Link
              to="/"
              className="mt-4 inline-block rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
            >
              進去看看
            </Link>
          </>
        )}
      </div>
    </div>
  );
}
