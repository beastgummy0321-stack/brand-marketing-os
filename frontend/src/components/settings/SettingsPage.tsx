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
  { value: "ai", label: "AI 金鑰與月費", icon: KeyRound, group: "AI 與費用" },
  { value: "models", label: "模型設定", icon: Sparkles, group: "AI 與費用" },
  { value: "budget", label: "品牌花費上限", icon: Wallet, group: "AI 與費用" },
  { value: "meta", label: "Meta 廣告連線", icon: Link2, group: "品牌與廣告" },
  { value: "rules", label: "品牌規則參數", icon: SlidersHorizontal, group: "品牌與廣告" },
] as const;

/** 分組一直掛載，切換頁籤或重新讀取設定不會丟失其他表單的草稿。 */
export function SettingsPage() {
  const [params, setParams] = useSearchParams();
  const activeTab = tabs.find((tab) => tab.value === params.get("tab"))?.value ?? "ai";
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

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title="設定" description="管理 AI 費用、廣告帳戶連線與品牌判讀參數。" />
      <div className="workspace-split">
        <nav className="workspace-subnav" aria-label="設定分類">
          {tabs.map((tab, index) => <div key={tab.value}>
            {(index === 0 || tabs[index - 1].group !== tab.group) && <p className="px-3 pb-2 pt-3 text-xs text-muted-foreground">{tab.group}</p>}
            <button type="button" className="w-full" aria-pressed={activeTab === tab.value} onClick={() => setParams((previous) => { const next = new URLSearchParams(previous); next.set("tab", tab.value); return next; })}>
              <tab.icon className="size-4" aria-hidden="true" />{tab.label}
            </button>
          </div>)}
        </nav>
        <div className="workspace-content max-w-[1100px]">
          {error && usesSharedSettings && <div role="alert" className="mb-4 flex items-center justify-between gap-4 rounded-lg border border-danger/25 bg-danger/5 p-4 text-sm"><p>{error}</p><Button variant="outline" onClick={load} disabled={loading}>重新載入</Button></div>}
          {!data && loading && usesSharedSettings && <div aria-label="設定載入中" className="flex flex-col gap-4"><Skeleton className="h-20" /><Skeleton className="h-80" /></div>}
          {data && <>
            {loading && usesSharedSettings && <p role="status" className="mb-3 text-sm text-muted-foreground">正在更新設定…</p>}
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
