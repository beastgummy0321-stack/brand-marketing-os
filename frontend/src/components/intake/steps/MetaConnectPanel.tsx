import { useEffect, useState } from "react";
import { Button } from "@/components/layout/ui/button";
import type { MetaAccountsData } from "@/lib/metaApi";
import {
  bindMetaAccount,
  connectMetaToken,
  fetchMetaAccounts,
  fetchMetaBackfillStatus,
  startMetaBackfill,
} from "@/lib/metaApi";
import { cn } from "@/lib/utils";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; meta: MetaAccountsData };

const BACKFILL_FAILED = "這次沒拉到，之後可以在設定頁重試。";

/** Meta's 接上／換一個 panel under its row in brand onboarding #/b6 (F42-I11). The interaction is the one the old
 * tools step had, lifted out unchanged: paste a token → pick one of the token's ad accounts → 「指定給這個品牌」 →
 * the spend history backfill starts in the background. The Meta client (`frontend/src/lib/metaApi.ts`) is the
 * same one the settings page uses; nothing new is connected here. Binding adds the account to the brand (the
 * existing bind semantics); an account already bound is shown as such. `onBound` lets the step re-read its
 * connector list so the row turns 「已接上」. */
export function MetaConnectPanel({ brandId, onBound }: { brandId: string; onBound: () => void }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [tokenInput, setTokenInput] = useState("");
  const [tokenError, setTokenError] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [selectedAccountId, setSelectedAccountId] = useState<string | null>(null);
  const [assigning, setAssigning] = useState(false);
  const [assignError, setAssignError] = useState<string | null>(null);
  const [backfilling, setBackfilling] = useState(false);
  const [backfillNote, setBackfillNote] = useState<string | null>(null);

  function load() {
    setState({ status: "loading" });
    fetchMetaAccounts()
      .then((meta) => setState({ status: "ready", meta }))
      .catch((err: unknown) => setState({ status: "error", message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。" }));
  }

  useEffect(load, []);

  async function handleConnectToken() {
    const token = tokenInput.trim();
    if (!token) {
      setTokenError("請貼上 Meta 存取權杖。");
      return;
    }
    setConnecting(true);
    setTokenError(null);
    try {
      const meta = await connectMetaToken(token);
      setTokenInput("");
      setState({ status: "ready", meta });
    } catch (err) {
      setTokenError(err instanceof Error ? err.message : "連接失敗，請稍後再試。");
    } finally {
      setConnecting(false);
    }
  }

  function pollBackfill() {
    fetchMetaBackfillStatus(brandId)
      .then((status) => {
        if (status.running) setTimeout(pollBackfill, 3000);
        else setBackfilling(false);
      })
      .catch(() => {
        setBackfilling(false);
        setBackfillNote(BACKFILL_FAILED);
      });
  }

  async function handleAssign() {
    if (!selectedAccountId) return;
    setAssigning(true);
    setAssignError(null);
    try {
      await bindMetaAccount(brandId, selectedAccountId);
      setBackfilling(true);
      startMetaBackfill(brandId)
        .then(() => pollBackfill())
        .catch(() => {
          setBackfilling(false);
          setBackfillNote(BACKFILL_FAILED);
        });
      setSelectedAccountId(null);
      fetchMetaAccounts().then((meta) => setState({ status: "ready", meta })).catch(() => undefined);
      onBound();
    } catch (err) {
      setAssignError(err instanceof Error ? err.message : "指定失敗，請稍後再試。");
    } finally {
      setAssigning(false);
    }
  }

  if (state.status === "loading") {
    return <p className="text-[12.5px] text-muted-foreground">讀取中…</p>;
  }
  if (state.status === "error") {
    return (
      <div className="flex flex-col items-start gap-1.5">
        <p role="alert" className="text-[12.5px] text-danger">{state.message}</p>
        <Button type="button" variant="link" className="h-auto p-0 text-[12.5px]" onClick={load}>重新載入</Button>
      </div>
    );
  }

  const { meta } = state;
  const hasToken = meta.token_tail !== null;

  return (
    <div data-slot="meta-connect" className="flex flex-col gap-2.5">
      {!hasToken && (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="text"
              value={tokenInput}
              onChange={(e) => setTokenInput(e.target.value)}
              placeholder="貼上 Meta 存取權杖"
              aria-label="Meta 存取權杖"
              className="min-w-[240px] flex-1 rounded-lg border border-input bg-card px-3 py-[7px] text-sm focus:border-primary focus:shadow-[0_0_0_3px_var(--color-accent)] focus:outline-none"
            />
            <Button type="button" variant="outline" size="sm" disabled={connecting} onClick={() => void handleConnectToken()}>
              {connecting ? "讀取中…" : "讀取帳戶"}
            </Button>
          </div>
          {tokenError && <span role="alert" className="text-xs text-danger">{tokenError}</span>}
        </div>
      )}

      {hasToken && (
        <div className="flex flex-col gap-2">
          {meta.accounts.length === 0 && <p className="text-[12.5px] text-muted-foreground">這把權杖沒有列出任何帳戶。</p>}
          {meta.accounts.map((acc) => {
            const bound = acc.bound_brand_ids.includes(brandId);
            const picked = selectedAccountId === acc.id;
            return (
              <label
                key={acc.id}
                className={cn(
                  "flex items-center gap-2 rounded-lg border px-3 py-2 text-sm",
                  bound ? "border-border bg-muted/40" : "cursor-pointer",
                  picked ? "border-primary bg-accent/50" : !bound && "border-border",
                )}
              >
                <input type="radio" name="meta-account" checked={picked} disabled={bound} onChange={() => setSelectedAccountId(acc.id)} />
                <span className="font-medium text-foreground">{acc.name}</span>
                <span className="numeric text-xs text-muted-foreground">{acc.account_id}</span>
                {bound && <span className="ml-auto text-xs text-success">已指定給這個品牌</span>}
              </label>
            );
          })}
          {assignError && <span role="alert" className="text-xs text-danger">{assignError}</span>}
          {meta.accounts.some((acc) => !acc.bound_brand_ids.includes(brandId)) && (
            <Button type="button" size="sm" className="self-start" disabled={!selectedAccountId || assigning} onClick={() => void handleAssign()}>
              {assigning ? "指定中…" : "指定給這個品牌"}
            </Button>
          )}
          {!meta.accounts.some((acc) => acc.bound_brand_ids.includes(brandId)) && (
            <p className="text-xs text-muted-foreground">權杖已存，還沒指定給這個品牌。</p>
          )}
        </div>
      )}

      {backfilling && (
        <div className="flex items-center gap-2 rounded-lg border border-dashed border-border bg-muted/40 px-3 py-2 text-[12.5px] text-muted-foreground">
          <span className="size-2 shrink-0 animate-pulse rounded-full bg-primary" />
          正在把過去的花費拉進來，大約幾分鐘，不影響你先往下走
        </div>
      )}
      {!backfilling && backfillNote && <p className="text-[12.5px] text-muted-foreground">{backfillNote}</p>}
    </div>
  );
}
