import { useEffect, useState } from "react";
import { SidePanel } from "@/components/layout/SidePanel";
import { setOrgId, signOut } from "@/lib/auth";
import { apiFetch } from "@/lib/http";
import { useFormSubmit } from "@/lib/useFormSubmit";

interface OrgOut {
  id: string;
  name: string;
  kind: string;
  role: string;
}

interface MeResponse {
  user: { id: string; email: string };
  org: OrgOut;
  orgs: OrgOut[];
}

interface InviteOut {
  id: string;
  email: string;
  role: string;
  expires_at: string;
}

interface CreateInviteResponse {
  invite: InviteOut;
  accept_url: string | null;
}

type Panel = null | "rename" | "invite";

/** 頂欄的組織選單（票 03-2 §3）：組織名稱、「我是公司／組織」（個人版→公司版）、
 * 邀請成員（owner 專用）、多組織時的切換器、登出。掛在 `Topbar.tsx`（見該檔），跟
 * `ActiveJobsBell` 同一排既有右側小工具並列，不是獨立路由。
 *
 * `GET /api/identity/me` 在這裡掛載時打一次——`AppShell`／`Topbar` 目前是每個路由各自
 * 掛一份（`App.tsx` 每個 `*Route` 函式各自 `<AppShell>`），所以嚴格說是「每次換頁重新
 * 掛載都打一次」，不是整個 session 只打一次；這跟 `ActiveJobsBell` 現有的做法一致
 * （沒有全站狀態快取層），本票不額外造一個 context／全域快取只為了這裡。 */
export function OrgMenu() {
  const [me, setMe] = useState<MeResponse | "loading" | "error">("loading");
  const [panel, setPanel] = useState<Panel>(null);
  const [companyName, setCompanyName] = useState("");
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteResult, setInviteResult] = useState<CreateInviteResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch("/api/identity/me")
      .then(async (res) => {
        if (cancelled) return;
        if (!res.ok) {
          setMe("error");
          return;
        }
        const body = (await res.json()) as MeResponse;
        setMe(body);
        // 票 03-3 §4：後端已經決定好落在哪個組織（沒帶 X-Org-Id 時用預設組織），把它記
        // 回 localStorage——不然單一組織的使用者永遠不會寫過 orgId，之後每次請求都要
        // 靠後端重新猜一次預設組織，多繞一手也少了「明確帶著自己組織打請求」這件事。
        setOrgId(body.org.id);
      })
      .catch(() => {
        if (!cancelled) setMe("error");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const renameForm = useFormSubmit(async () => {
    const res = await apiFetch("/api/identity/orgs/current/rename", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: companyName.trim() }),
    });
    if (!res.ok) throw new Error(`改名失敗（狀態碼 ${res.status}）`);
    const org = (await res.json()) as OrgOut;
    setMe((prev) => (prev === "loading" || prev === "error" ? prev : { ...prev, org, orgs: prev.orgs.map((o) => (o.id === org.id ? org : o)) }));
    setPanel("invite");
  });

  const inviteForm = useFormSubmit(async () => {
    const res = await apiFetch("/api/identity/invites", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: inviteEmail.trim(), role: "member" }),
    });
    if (!res.ok) throw new Error(`邀請失敗（狀態碼 ${res.status}）`);
    setInviteResult((await res.json()) as CreateInviteResponse);
    setInviteEmail("");
  });

  if (me === "loading" || me === "error") return null;

  function switchOrg(orgId: string) {
    setOrgId(orgId);
    // 換組織之後每個畫面的品牌清單都不一樣，最省事的做法是整頁重新載入——所有畫面本來
    // 就各自在掛載時打一次自己的 API，不用另外造一套「換組織要通知誰重新讀資料」的機制。
    window.location.reload();
  }

  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="text-muted-foreground">{me.org.name}</span>

      {me.org.kind === "personal" && (
        <button
          type="button"
          onClick={() => setPanel("rename")}
          className="rounded-md border border-border px-3 py-1 text-xs font-medium text-muted-foreground hover:border-primary hover:text-primary"
        >
          我是公司／組織
        </button>
      )}

      {me.org.role === "owner" && me.org.kind !== "personal" && (
        <button
          type="button"
          onClick={() => setPanel("invite")}
          className="rounded-md border border-border px-3 py-1 text-xs font-medium text-muted-foreground hover:border-primary hover:text-primary"
        >
          邀請成員
        </button>
      )}

      {me.orgs.length > 1 && (
        <select
          aria-label="切換組織"
          value={me.org.id}
          onChange={(e) => switchOrg(e.target.value)}
          className="rounded-md border border-border bg-card px-2 py-1 text-xs text-foreground"
        >
          {me.orgs.map((o) => (
            <option key={o.id} value={o.id}>
              {o.name}
            </option>
          ))}
        </select>
      )}

      <button
        type="button"
        onClick={() => void signOut()}
        className="text-xs text-muted-foreground hover:underline"
      >
        登出
      </button>

      {panel === "rename" && (
        <SidePanel ariaLabel="設定公司／組織名稱" onClose={() => setPanel(null)}>
          <div className="border-b border-border pb-4">
            <h2 className="font-display text-lg text-foreground">設定公司／組織名稱</h2>
            <p className="mt-1 text-sm text-muted-foreground">改完之後可以直接邀請同事加入。</p>
          </div>
          <form
            className="flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              void renameForm.submit();
            }}
          >
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium text-foreground">公司／組織名稱</span>
              <input
                type="text"
                required
                value={companyName}
                onChange={(e) => setCompanyName(e.target.value)}
                className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
              />
            </label>
            {renameForm.error && <p className="text-sm text-danger">{renameForm.error}</p>}
            <button
              type="submit"
              disabled={renameForm.saving}
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {renameForm.saving ? "儲存中…" : "儲存並邀請成員"}
            </button>
          </form>
        </SidePanel>
      )}

      {panel === "invite" && (
        <SidePanel ariaLabel="邀請成員" onClose={() => setPanel(null)}>
          <div className="border-b border-border pb-4">
            <h2 className="font-display text-lg text-foreground">邀請成員</h2>
            <p className="mt-1 text-sm text-muted-foreground">輸入 email，對方會拿到一個加入連結。</p>
          </div>
          <form
            className="flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              void inviteForm.submit();
            }}
          >
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium text-foreground">Email</span>
              <input
                type="email"
                required
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
                className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
              />
            </label>
            {inviteForm.error && <p className="text-sm text-danger">{inviteForm.error}</p>}
            <button
              type="submit"
              disabled={inviteForm.saving}
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {inviteForm.saving ? "送出中…" : "送出邀請"}
            </button>
          </form>

          {inviteResult && (
            <div className="rounded-md border border-border bg-muted/40 p-3 text-sm">
              {inviteResult.accept_url ? (
                <>
                  <p className="text-foreground">本機開發環境不寄信，把這個連結給對方：</p>
                  <div className="mt-2 flex items-center gap-2">
                    <input
                      readOnly
                      value={`${window.location.origin}${inviteResult.accept_url}`}
                      className="flex-1 rounded-md border border-border bg-card px-2 py-1 text-xs text-foreground"
                      onFocus={(e) => e.currentTarget.select()}
                    />
                    <button
                      type="button"
                      onClick={() => void navigator.clipboard.writeText(`${window.location.origin}${inviteResult.accept_url}`)}
                      className="rounded-md border border-border px-2 py-1 text-xs font-medium text-muted-foreground hover:border-primary hover:text-primary"
                    >
                      複製
                    </button>
                  </div>
                </>
              ) : (
                <p className="text-foreground">邀請信已經寄出。</p>
              )}
            </div>
          )}
        </SidePanel>
      )}
    </div>
  );
}
