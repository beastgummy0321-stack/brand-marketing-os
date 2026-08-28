import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { apiFetch } from "@/lib/http";

interface AcceptInviteResponse {
  org: { id: string; name: string; kind: string; role: string };
}

interface ErrorEnvelope {
  error: { code: string; message: string };
}

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "done"; orgName: string };

/** 接受邀請頁（票 03-2）：路由 `/accept-invite?token=…`（`App.tsx`）。刻意不掛在
 * `App.tsx` 的登入守門之下——沒登入時 `apiFetch` 打 401，`lib/http.ts` 的攔截器自己會
 * 導去 `/login`，這裡不用重複判斷「有沒有登入」。錯誤文字直接用後端錯誤信封的
 * `message`（票面「不要自己發明新的措辭」），不是自己另外寫一套。 */
export function AcceptInvitePage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    if (!token) {
      setState({ status: "error", message: "這個邀請連結少了 token，請跟邀請你的人要一份新的連結。" });
      return;
    }
    let cancelled = false;
    apiFetch(`/api/identity/invites/${encodeURIComponent(token)}/accept`, { method: "POST" })
      .then(async (res) => {
        if (cancelled) return;
        if (!res.ok) {
          const body = (await res.json().catch(() => null)) as ErrorEnvelope | null;
          setState({
            status: "error",
            message: body?.error.message ?? `加入失敗（狀態碼 ${res.status}）`,
          });
          return;
        }
        const body = (await res.json()) as AcceptInviteResponse;
        setState({ status: "done", orgName: body.org.name });
      })
      .catch(() => {
        if (!cancelled) setState({ status: "error", message: "加入失敗，請稍後再試。" });
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  return (
    <div className="flex h-full items-center justify-center bg-background">
      <div className="w-full max-w-sm rounded-[var(--radius-xl)] border border-border bg-card p-8 text-center shadow-[var(--shadow-card)]">
        {state.status === "loading" && <p className="text-sm text-muted-foreground">處理邀請中…</p>}
        {state.status === "error" && (
          <>
            <p className="text-sm text-danger">{state.message}</p>
            <Link to="/" className="mt-4 inline-block text-sm text-primary hover:underline">
              回到首頁
            </Link>
          </>
        )}
        {state.status === "done" && (
          <>
            <p className="text-sm text-foreground">已經加入「{state.orgName}」。</p>
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
