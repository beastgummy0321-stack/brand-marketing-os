import { useEffect, useState, type ReactNode } from "react";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import type { SettingsData } from "@/lib/settingsApi";
import { fetchSettings } from "@/lib/settingsApi";
import { ApiKeySection } from "./ApiKeySection";
import { AssetsSection } from "./AssetsSection";
import { Ga4Section } from "./Ga4Section";
import { MetaSection } from "./MetaSection";
import { ModelSection } from "./ModelSection";
import { AutonomySection } from "./AutonomySection";
import { RuleCardsSection } from "./RuleCardsSection";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: SettingsData };

/** 設定頁（S15，票 B1-settings）：合併舊版三個入口（settings／settings_hub／
 * settings_ads 的規則卡部分）。六個不分品牌小節共讀一份 `/api/settings`，任一小節儲存
 * 成功後整頁重新讀取（沿用駕駛艙 AlertsPanel／CockpitPage 的既有慣例：呼叫端不各自維護
 * 分散的 state，統一由上層重讀一次）。品牌規則卡區塊資料源不同、自己管自己的載入狀態。 */
export function SettingsPage() {
  const [state, setState] = useState<LoadState>({ status: "loading" });

  function load() {
    setState({ status: "loading" });
    fetchSettings()
      .then((data) => setState({ status: "ready", data }))
      .catch((err: unknown) =>
        setState({
          status: "error",
          message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。",
        }),
      );
  }

  useEffect(load, []);

  let content: ReactNode;
  if (state.status === "loading") {
    content = (
      <div className="flex flex-col gap-5">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-32" />
        ))}
        {/* 規則卡骨架不等 /api/settings：RuleCardsSection 自己讀 /api/dashboard/overview，
            掛載當下就會自己顯示骨架（見該檔），跟整頁 loading 態同框即可，不用另外複製一份。 */}
        <RuleCardsSection />
      </div>
    );
  } else if (state.status === "error") {
    content = (
      <EmptyState
        title="讀取失敗"
        description={state.message}
        onAction={load}
        actionLabel="重新載入"
      />
    );
  } else {
    const { data } = state;
    content = (
      <div className="flex flex-col gap-5">
        <MetaSection data={data} onSaved={load} />
        <Ga4Section data={data} onSaved={load} />
        <ApiKeySection data={data} onSaved={load} />
        <ModelSection data={data} onSaved={load} />
        <AssetsSection data={data} onSaved={load} />
        <AutonomySection />
        <RuleCardsSection />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <Breadcrumb items={[{ label: "跨品牌總覽", href: "/" }, { label: "設定" }]} />
      <h1 className="font-display text-2xl text-foreground">設定</h1>
      {content}
    </div>
  );
}
