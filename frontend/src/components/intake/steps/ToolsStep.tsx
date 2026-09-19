import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import type { MetaAccount, MetaAccountsData } from "@/lib/metaApi";
import {
  bindMetaAccount,
  connectMetaToken,
  fetchMetaAccounts,
  fetchMetaBackfillStatus,
  startMetaBackfill,
} from "@/lib/metaApi";
import type { IntakeToolsData } from "@/lib/intakeApi";
import { fetchIntakeTools, saveConversionGoal } from "@/lib/intakeApi";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; tools: IntakeToolsData; meta: MetaAccountsData };

const SKIP_NOTE = "還沒接上廣告帳戶，之後建立 Campaign 時系統會提醒你補。";

/** 精靈第 4 步「接工具」（F05-I08）：Meta 廣告帳戶＋成效目標，GA4 是灰色保留席。
 * 不新做 Meta 的連線／綁定——`bindMetaAccount`／`connectMetaToken` 直接沿用
 * `frontend/src/lib/metaApi.ts`（既有設定頁在用的同一支 client）。這一步的「完成」＝
 * 「已指定給這個品牌」，不是「已貼權杖」；可以整步跳過，跳過不寫成拒絕。 */
export function ToolsStep({ brandId, onNext }: { brandId: string; onNext: () => void }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [tokenInput, setTokenInput] = useState("");
  const [tokenError, setTokenError] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [selectedAccountId, setSelectedAccountId] = useState<string | null>(null);
  const [assigning, setAssigning] = useState(false);
  const [assignError, setAssignError] = useState<string | null>(null);
  const [backfilling, setBackfilling] = useState(false);
  const [backfillNote, setBackfillNote] = useState<string | null>(null);
  const [goalError, setGoalError] = useState<string | null>(null);
  const [savingGoal, setSavingGoal] = useState(false);

  function load() {
    setState({ status: "loading" });
    Promise.all([fetchIntakeTools(brandId), fetchMetaAccounts()])
      .then(([tools, meta]) => setState({ status: "ready", tools, meta }))
      .catch((err: unknown) =>
        setState({ status: "error", message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。" }),
      );
  }

  useEffect(load, [brandId]);

  if (state.status === "loading") {
    return <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">讀取中…</div>;
  }
  if (state.status === "error") {
    return (
      <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-6">
        <p className="text-sm text-danger">{state.message}</p>
        <button type="button" onClick={load} className="self-start text-sm font-medium text-primary hover:underline">
          重新載入
        </button>
        <p className="text-sm text-muted-foreground">目前無法確認帳戶與目標設定，仍可先起草計畫，投放前再確認連線。</p>
        <Button asChild className="self-start"><Link to={`/brands/${encodeURIComponent(brandId)}/ads/new`}>先建立投放計畫</Link></Button>
      </div>
    );
  }

  const { tools, meta } = state;
  const hasToken = meta.token_tail !== null;
  const assignedAccountId = tools.bound_account_ids[0] ?? null;
  const assignedAccount = meta.accounts.find((a: MetaAccount) => a.id === assignedAccountId) ?? null;

  async function handleConnectToken() {
    const token = tokenInput.trim();
    if (!token) {
      setTokenError("請貼上 Meta 存取權杖。");
      return;
    }
    setConnecting(true);
    setTokenError(null);
    try {
      const data = await connectMetaToken(token);
      setTokenInput("");
      setState({ status: "ready", tools, meta: data });
    } catch (err) {
      setTokenError(err instanceof Error ? err.message : "連接失敗，請稍後再試。");
    } finally {
      setConnecting(false);
    }
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
        .catch(() => setBackfillNote("這次沒拉到，之後可以在設定頁重試。"));
      load();
    } catch (err) {
      setAssignError(err instanceof Error ? err.message : "指定失敗，請稍後再試。");
    } finally {
      setAssigning(false);
    }
  }

  function pollBackfill() {
    fetchMetaBackfillStatus(brandId)
      .then((status) => {
        if (status.running) {
          setTimeout(pollBackfill, 3000);
        } else {
          setBackfilling(false);
        }
      })
      .catch(() => {
        setBackfilling(false);
        setBackfillNote("這次沒拉到，之後可以在設定頁重試。");
      });
  }

  async function handleSelectGoal(goal: string) {
    setSavingGoal(true);
    setGoalError(null);
    try {
      await saveConversionGoal(brandId, goal);
      load();
    } catch (err) {
      setGoalError(err instanceof Error ? err.message : "儲存失敗，請稍後再試。");
    } finally {
      setSavingGoal(false);
    }
  }

  return (
    <div className="flex flex-col gap-5 rounded-lg border border-border bg-card p-6 shadow-card">
      <h2 className="font-display text-lg text-foreground">接工具</h2>

      <div className="flex flex-col gap-3 rounded-md border border-border p-4">
        <p className="text-sm font-medium text-foreground">Meta 廣告帳戶</p>

        {!hasToken && (
          <div className="flex flex-col gap-2">
            <input
              type="text"
              value={tokenInput}
              onChange={(e) => setTokenInput(e.target.value)}
              placeholder="貼上 Meta 存取權杖"
              className="rounded-md border border-border px-3 py-2 text-sm"
            />
            {tokenError && <span className="text-xs text-danger">{tokenError}</span>}
            <button
              type="button"
              onClick={() => void handleConnectToken()}
              disabled={connecting}
              className="self-start rounded-md border border-primary px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {connecting ? "讀取中…" : "讀取帳戶"}
            </button>
          </div>
        )}

        {hasToken && !assignedAccountId && (
          <div className="flex flex-col gap-2">
            {meta.accounts.length === 0 && (
              <p className="text-sm text-muted-foreground">這把權杖沒有列出任何帳戶。</p>
            )}
            {meta.accounts.map((acc) => (
              <label
                key={acc.id}
                className={`flex cursor-pointer items-center gap-2 rounded-md border p-2.5 text-sm ${
                  selectedAccountId === acc.id ? "border-primary bg-primary/5" : "border-border"
                }`}
              >
                <input
                  type="radio"
                  checked={selectedAccountId === acc.id}
                  onChange={() => setSelectedAccountId(acc.id)}
                />
                <span className="font-medium text-foreground">{acc.name}</span>
                <span className="numeric text-xs text-muted-foreground">{acc.account_id}</span>
              </label>
            ))}
            {assignError && <span className="text-xs text-danger">{assignError}</span>}
            {meta.accounts.length > 0 && (
              <button
                type="button"
                disabled={!selectedAccountId || assigning}
                onClick={() => void handleAssign()}
                className="self-start rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {assigning ? "指定中…" : "指定給這個品牌"}
              </button>
            )}
          </div>
        )}

        {assignedAccountId && (
          <p className="text-sm text-foreground">
            已指定給這個品牌：{assignedAccount ? assignedAccount.name : assignedAccountId}
          </p>
        )}

        {hasToken && !assignedAccountId && (
          <p className="text-xs text-muted-foreground">權杖已存，還沒指定給這個品牌。</p>
        )}

        {backfilling && (
          <div className="flex items-center gap-2 rounded-md border border-dashed border-border bg-muted/40 p-3 text-sm text-muted-foreground">
            <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-primary" />
            正在把過去的花費拉進來，大約幾分鐘，不影響你先往下走
          </div>
        )}
        {!backfilling && backfillNote && <p className="text-sm text-muted-foreground">{backfillNote}</p>}
      </div>

      <div className="flex flex-col gap-3 rounded-md border border-border p-4">
        <p className="text-sm font-medium text-foreground">成效目標</p>
        <p className="text-xs text-muted-foreground">這決定系統把什麼算成一次成效。</p>
        {tools.conversion_goal_options.map((g) => (
          <label
            key={g.key}
            className={`flex cursor-pointer items-center gap-2 rounded-md border p-3 text-sm ${
              tools.conversion_goal === g.key ? "border-primary bg-primary/5" : "border-border"
            }`}
          >
            <input
              type="radio"
              checked={tools.conversion_goal === g.key}
              disabled={savingGoal}
              onChange={() => void handleSelectGoal(g.key)}
            />
            <span className="font-medium text-foreground">{g.label}</span>
          </label>
        ))}
        {goalError && <span className="text-xs text-danger">{goalError}</span>}
      </div>

      <div className="flex cursor-not-allowed items-center justify-between rounded-md border border-dashed border-border bg-muted/40 p-4 text-sm text-muted-foreground">
        <span className="font-medium">GA4</span>
        <span>GA4 接上後開放</span>
      </div>

      <p className="text-sm text-muted-foreground">已保存的商品、成效目標與帳戶可沿用。你可以先建立計畫；品牌研究進度會保留，稍後仍可回來補充。</p>
      <div className="flex flex-wrap items-center gap-3">
        <Button asChild><Link to={`/brands/${encodeURIComponent(brandId)}/ads/new`}>先建立投放計畫</Link></Button>
        <Button type="button" variant="outline" onClick={onNext}>繼續品牌研究（選用）</Button>
        <Link className="text-sm text-primary underline" to={`/brands/${encodeURIComponent(brandId)}/ads`}>查看投放中心與月額度</Link>
      </div>
      {!assignedAccountId && <p className="text-xs text-muted-foreground">{SKIP_NOTE}</p>}
    </div>
  );
}
