import { formatUsd } from "@/lib/format";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { KeyRound, SlidersHorizontal, Sparkles, Wallet, Link2 } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Skeleton } from "@/components/layout/Skeleton";
import { Button } from "@/components/layout/ui/button";
import type { SettingsData } from "@/lib/settingsApi";
import { fetchSettings } from "@/lib/settingsApi";
import { ApiKeySection } from "./ApiKeySection";
import { SpendCapSection } from "./SpendCapSection";
import { ModelSection } from "./ModelSection";
import { MetaSection } from "./MetaSection";
import { RuleCardsSection } from "./RuleCardsSection";

const tabs = [
  { value: "budget", label: "品牌 AI 費用上限", icon: Wallet, advanced: false },
  { value: "meta", label: "Meta 廣告連線", icon: Link2, advanced: false },
  { value: "ai", label: "AI 金鑰與月費", icon: KeyRound, advanced: true },
  { value: "models", label: "模型設定", icon: Sparkles, advanced: true },
  { value: "rules", label: "品牌規則參數", icon: SlidersHorizontal, advanced: true },
] as const;

const commonTabs = tabs.filter((tab) => !tab.advanced);
const advancedTabs = tabs.filter((tab) => tab.advanced);

/** 分組一直掛載，切換頁籤或重新讀取設定不會丟失其他表單的草稿。 */
export function SettingsPage() {
  const [params, setParams] = useSearchParams();
  const activeTab = tabs.find((tab) => tab.value === params.get("tab"))?.value ?? "budget";
  const [advancedOpen, setAdvancedOpen] = useState(() => advancedTabs.some((tab) => tab.value === activeTab));
  const usesSharedSettings = activeTab === "ai" || activeTab === "models" || activeTab === "budget";
  const [data, setData] = useState<SettingsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const requestId = useRef(0);

  function load() {
    const id = ++requestId.current;
    setLoading(true);
    setError(null);
    fetchSettings()
      .then((next) => { if (requestId.current === id) setData(next); })
      .catch((err: unknown) => {
        if (requestId.current === id) setError(err instanceof Error ? err.message : "讀取失敗，請稍後再試。");
      })
      .finally(() => { if (requestId.current === id) setLoading(false); });
  }

  useEffect(() => { load(); return () => { requestId.current += 1; }; }, []);
  useEffect(() => {
    if (advancedTabs.some((tab) => tab.value === activeTab)) setAdvancedOpen(true);
  }, [activeTab]);

  function selectTab(value: (typeof tabs)[number]["value"]) {
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      next.set("tab", value);
      return next;
    });
  }

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title="設定" description="管理 AI 費用、廣告帳戶連線與品牌判讀參數。" />
      <div className="workspace-split">
        <nav className="workspace-subnav" aria-label="設定分類">
          <p className="px-3 pb-2 pt-3 text-xs text-muted-foreground">常用設定</p>
          {commonTabs.map((tab) => <button key={tab.value} type="button" className="w-full" aria-pressed={activeTab === tab.value} onClick={() => selectTab(tab.value)}>
              <tab.icon className="size-4" aria-hidden="true" />{tab.label}
          </button>)}
          <details
            className="mt-2 border-t border-border pt-2"
            open={advancedOpen}
            onToggle={(event) => setAdvancedOpen(event.currentTarget.open)}
          >
            <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-foreground">進階設定</summary>
            <div className="flex flex-col gap-1 pt-1">
              {advancedTabs.map((tab) => <button key={tab.value} type="button" className="w-full" aria-pressed={activeTab === tab.value} onClick={() => selectTab(tab.value)}>
                <tab.icon className="size-4" aria-hidden="true" />{tab.label}
              </button>)}
            </div>
          </details>
        </nav>
        <div className="workspace-content max-w-[1100px]">
          {error && usesSharedSettings && <div role="alert" className="mb-4 flex items-center justify-between gap-4 rounded-lg border border-danger/25 bg-danger/5 p-4 text-sm"><p>{error}</p><Button variant="outline" onClick={load} busy={loading}>重新載入</Button></div>}
          {!data && loading && usesSharedSettings && <div aria-label="設定載入中" className="flex flex-col gap-4"><Skeleton className="h-20" /><Skeleton className="h-80" /></div>}
          {data && <>
            {loading && usesSharedSettings && <p role="status" className="mb-3 text-sm text-muted-foreground">正在更新設定…</p>}
            <div hidden={activeTab !== "budget"} className="mb-4 rounded-lg border border-border bg-muted/30 p-4">
              <p className="text-sm font-medium text-foreground">整個組織本月 AI 費用</p>
              <p className="mt-1 text-sm text-muted-foreground">
                已使用 {formatUsd(data.ai_monthly_spend)}／上限 {formatUsd(data.ai_monthly_cost_limit)}
                {data.ai_cap_applies ? "；月底前達到上限會停止新的 AI 呼叫。" : "；使用自有金鑰時，此上限僅供參考。"}
              </p>
              <button type="button" className="mt-2 text-sm font-medium text-primary hover:underline" onClick={() => selectTab("ai")}>
                查看 AI 金鑰與月費
              </button>
            </div>
            <div hidden={activeTab !== "ai"}><ApiKeySection data={data} onSaved={load} /></div>
            <div hidden={activeTab !== "models"}><ModelSection data={data} onSaved={load} /></div>
            <div hidden={activeTab !== "budget"}><SpendCapSection data={data} onSaved={load} /></div>
          </>}
          <div hidden={activeTab !== "meta"}><MetaSection /></div>
          <div hidden={activeTab !== "rules"}><RuleCardsSection /></div>
        </div>
      </div>
    </div>
  );
}
