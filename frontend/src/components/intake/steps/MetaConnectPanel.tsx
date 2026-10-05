import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/layout/ui/button";
import type { MetaAccountsData, MetaBackfillStatus } from "@/lib/metaApi";
import {
  bindMetaAccount,
  connectMetaToken,
  fetchMetaAccounts,
  fetchMetaBackfillStatus,
  startMetaBackfill,
} from "@/lib/metaApi";
import { cn } from "@/lib/utils";
import { BackfillOutcomeLine } from "../HistoryPage";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; meta: MetaAccountsData };

const STATUS_READ_FAILED = "讀不到拉過去花費的進度，請稍後再試。";
const START_FAILED = "沒能開始拉過去的花費，請再試一次。";

function errorText(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

/** Meta's 接上／再接一個帳戶 panel under its row in brand onboarding #/b6 (F42-I11). The interaction is the one the old
 * tools step had: paste a token → pick one of the token's ad accounts, which assigns it to the brand at once (F46-I09;
 * no separate 「指定給這個品牌」 click) → the spend history backfill starts in the background. The Meta client (`frontend/src/lib/metaApi.ts`) is the
 * same one the settings page uses; nothing new is connected here. Binding adds the account to the brand (the
 * existing bind semantics); an account already bound is shown as such. `onBound` lets the step re-read its
 * connector list so the row turns 「已接上」. F47 Contract G: a token Meta refused, could not be read with, or that
 * lists no account is not stored and the token input stays with the server's sentence; a stored token offers
 * 「換一把權杖」. F50-I16 (Contract J): the backfill line reads the stored outcome (`GET …/backfill`), also when the panel
 * opens on a brand already bound — running, done with the range, empty, or failed with 「再試一次」; a failed read says
 * so; the poll stops on unmount. */
export function MetaConnectPanel({ brandId, onBound }: { brandId: string; onBound: () => void }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [tokenInput, setTokenInput] = useState("");
  const [tokenError, setTokenError] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  /** 換一把權杖 was pressed while a token is stored: the token input shows again (it stays after a failure). */
  const [replacing, setReplacing] = useState(false);
  /** The account being assigned right now (its radio shows picked and the row says 指定中…). */
  const [assigningId, setAssigningId] = useState<string | null>(null);
  const [assignError, setAssignError] = useState<string | null>(null);
  const [backfilling, setBackfilling] = useState(false);
  const [backfill, setBackfill] = useState<MetaBackfillStatus | null>(null);
  /** A failed status read or start, shown instead of nothing. */
  const [backfillError, setBackfillError] = useState<{ message: string; retry: "read" | "start" } | null>(null);
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      if (pollTimer.current) clearTimeout(pollTimer.current);
      pollTimer.current = null;
    };
  }, []);

  function boundHere(meta: MetaAccountsData): boolean {
    return meta.accounts.some((acc) => acc.bound_brand_ids.includes(brandId));
  }

  function load() {
    setState({ status: "loading" });
    fetchMetaAccounts()
      .then((meta) => {
        setState({ status: "ready", meta });
        // A brand already bound may have a pull running or ended: show it after a reload too.
        if (boundHere(meta)) readBackfill();
      })
      .catch((err: unknown) => setState({ status: "error", message: errorText(err, "讀取失敗，請稍後再試。") }));
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps -- read once on open; reloads go through the 重新載入 button
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
      setReplacing(false);
      setState({ status: "ready", meta });
    } catch (err) {
      setTokenError(err instanceof Error ? err.message : "連接失敗，請稍後再試。");
    } finally {
      setConnecting(false);
    }
  }

  function readBackfill() {
    if (pollTimer.current) clearTimeout(pollTimer.current);
    pollTimer.current = null;
    fetchMetaBackfillStatus(brandId)
      .then((status) => {
        if (!alive.current) return;
        setBackfill(status);
        setBackfillError(null);
        setBackfilling(status.running);
        if (status.running) pollTimer.current = setTimeout(readBackfill, 3000);
      })
      .catch((err: unknown) => {
        if (!alive.current) return;
        setBackfilling(false);
        setBackfillError({ message: errorText(err, STATUS_READ_FAILED), retry: "read" });
      });
  }

  function startBackfill() {
    setBackfilling(true);
    setBackfill(null);
    setBackfillError(null);
    startMetaBackfill(brandId)
      .then(() => {
        if (alive.current) readBackfill();
      })
      .catch((err: unknown) => {
        if (!alive.current) return;
        setBackfilling(false);
        setBackfillError({ message: errorText(err, START_FAILED), retry: "start" });
      });
  }

  async function handleAssign(accountId: string) {
    if (assigningId) return;
    setAssigningId(accountId);
    setAssignError(null);
    try {
      await bindMetaAccount(brandId, accountId);
      startBackfill();
      fetchMetaAccounts()
        .then((meta) => setState({ status: "ready", meta }))
        .catch((err: unknown) => setAssignError(errorText(err, "帳戶清單讀取失敗，請重新整理再看一次。")));
      onBound();
    } catch (err) {
      setAssignError(err instanceof Error ? err.message : "指定失敗，請稍後再試。");
    } finally {
      // A failure leaves the radio unpicked; a success re-reads the list, where the account reads as bound.
      setAssigningId(null);
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
  // F47 Contract G (drill-10 R3): the token input never disappears after a failure; a stored token that lists no
  // account (stored before tokens without accounts were refused) shows it at once.
  const showTokenInput = !hasToken || replacing || meta.accounts.length === 0;

  return (
    <div data-slot="meta-connect" className="flex flex-col gap-2.5">
      {showTokenInput && (
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

      {hasToken && meta.accounts.length > 0 && (
        <div className="flex flex-col gap-2">
          {meta.accounts.map((acc) => {
            const bound = acc.bound_brand_ids.includes(brandId);
            const picked = assigningId === acc.id;
            return (
              <label
                key={acc.id}
                className={cn(
                  "flex items-center gap-2 rounded-lg border px-3 py-2 text-sm",
                  bound ? "border-border bg-muted/40" : "cursor-pointer",
                  picked ? "border-primary bg-accent/50" : !bound && "border-border",
                )}
              >
                <input type="radio" name="meta-account" checked={picked} disabled={bound || assigningId !== null}
                  onChange={() => void handleAssign(acc.id)} />
                <span className="font-medium text-foreground">{acc.name}</span>
                <span className="numeric text-xs text-muted-foreground">{acc.account_id}</span>
                {bound && <span className="ml-auto text-xs text-success">已指定給這個品牌</span>}
                {picked && <span role="status" className="ml-auto text-xs text-muted-foreground">指定中…</span>}
              </label>
            );
          })}
          {assignError && <span role="alert" className="text-xs text-danger">{assignError}</span>}
          {meta.accounts.length > 0 && !meta.accounts.some((acc) => acc.bound_brand_ids.includes(brandId)) && (
            <p className="text-xs text-muted-foreground">權杖已存，還沒指定給這個品牌。</p>
          )}
          {!showTokenInput && (
            <div>
              <Button type="button" variant="link" className="h-auto p-0 text-[12.5px]" onClick={() => setReplacing(true)}>
                換一把權杖
              </Button>
            </div>
          )}
        </div>
      )}

      {backfilling && (
        <div className="flex items-center gap-2 rounded-lg border border-dashed border-border bg-muted/40 px-3 py-2 text-[12.5px] text-muted-foreground">
          <span className="size-2 shrink-0 animate-pulse rounded-full bg-primary" />
          正在把過去的花費拉進來，大約幾分鐘，不影響你先往下走
        </div>
      )}
      {!backfilling && <BackfillOutcomeLine backfill={backfill} retrying={false} onRetry={startBackfill} compact />}
      {!backfilling && backfillError && (
        <div className="flex flex-col items-start gap-1.5">
          <p role="alert" className="text-[12.5px] text-danger">{backfillError.message}</p>
          <Button type="button" variant="link" className="h-auto p-0 text-[12.5px]"
            onClick={backfillError.retry === "start" ? startBackfill : readBackfill}>
            {backfillError.retry === "start" ? "再試一次" : "重新載入"}
          </Button>
        </div>
      )}
    </div>
  );
}
