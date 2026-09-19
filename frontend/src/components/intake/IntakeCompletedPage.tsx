import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { Skeleton } from "@/components/layout/Skeleton";
import { fetchPersonas, fetchTruthCard, type PersonaBundle, type TruthCard } from "@/lib/intakeT2Api";
import { fetchLibrary } from "@/lib/libraryApi";
import { fetchLaunchReadiness, type LaunchReadiness } from "@/lib/adsLaunchApi";
import { ReadinessList } from "@/components/ads";

type TruthState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: TruthCard };

type OptionalState<T> =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: T };

export function IntakeCompletedPage({ brandId, onRestart }: { brandId: string; onRestart: () => void }) {
  const [truth, setTruth] = useState<TruthState>({ status: "loading" });
  const [personas, setPersonas] = useState<OptionalState<PersonaBundle>>({ status: "loading" });
  const [readiness, setReadiness] = useState<OptionalState<LaunchReadiness>>({ status: "loading" });
  // 投放歷史只決定是否顯示回顧入口，不代表目前活動已匯入。
  const [advertisingHistory, setAdvertisingHistory] = useState<"has_history" | "none" | null>(null);

  function load() {
    setTruth({ status: "loading" });
    setPersonas({ status: "loading" });
    setReadiness({ status: "loading" });
    fetchTruthCard(brandId)
      .then((data) => setTruth({ status: "ready", data }))
      .catch((err: unknown) => setTruth({ status: "error", message: err instanceof Error ? err.message : "讀取完成結果失敗。" }));
    fetchPersonas(brandId)
      .then((data) => setPersonas({ status: "ready", data }))
      .catch((err: unknown) => setPersonas({ status: "error", message: err instanceof Error ? err.message : "讀取人物誌狀態失敗。" }));
    fetchLibrary(brandId)
      .then((data) => setAdvertisingHistory(data.brand.advertising_history))
      .catch(() => setAdvertisingHistory(null));
    fetchLaunchReadiness(brandId)
      .then((data) => setReadiness({ status: "ready", data }))
      .catch((err: unknown) => setReadiness({ status: "error", message: err instanceof Error ? err.message : "讀取可投放檢查表失敗。" }));
  }

  useEffect(load, [brandId]);

  if (truth.status === "loading") {
    return <div className="flex flex-col gap-3"><Skeleton className="h-24" /><Skeleton className="h-20" /></div>;
  }
  if (truth.status === "error") {
    return (
      <div className="flex flex-col gap-3 rounded-lg border border-danger/40 bg-danger/5 p-6 text-sm">
        <p className="font-medium text-danger">建檔已完成，但完成畫面暫時讀不到</p>
        <p className="text-muted-foreground">{truth.message}</p>
        <div><button type="button" onClick={load} className="rounded-md border border-border px-3 py-1.5 font-medium text-foreground hover:border-primary hover:text-primary">重新讀取</button></div>
        <Link className="text-primary underline" to={`/brands/${encodeURIComponent(brandId)}/ads`}>前往投放中心</Link>
      </div>
    );
  }

  const count = truth.data.accepted.length + truth.data.needs_confirmation.length + truth.data.forbidden.length;
  return (
    <div className="flex max-w-3xl flex-col gap-4">
      <div className="rounded-lg border border-border bg-card p-6 shadow-[var(--shadow-card)]">
        <h1 className="font-display text-2xl text-foreground">🎉 建檔完成</h1>
        <p className="mt-2 text-sm text-muted-foreground">{count === 0 ? "這次沒有新增資料，但建檔流程已完成。" : "品牌資料 " + count + " 條已生效。"}</p>
      </div>
      <ReadinessCard state={readiness} />
      <PersonaProgress state={personas} />
      <Link className="text-sm text-primary underline" to={`/brands/${encodeURIComponent(brandId)}/library?tab=customer-voice`}>查看與修正人物誌</Link>
      <div className="flex flex-wrap gap-3">
        <Button asChild><Link to={`/brands/${encodeURIComponent(brandId)}/ads/new`}>建立投放計畫</Link></Button>
        <Button asChild variant="outline"><Link to={`/brands/${encodeURIComponent(brandId)}/ads`}>前往投放中心</Link></Button>
        <Button asChild variant="outline"><Link to={"/brands/" + encodeURIComponent(brandId)}>前往品牌頁</Link></Button>
        <Button type="button" variant="outline" onClick={onRestart}>再跑一次調研</Button>
      </div>
      <p className="text-sm text-muted-foreground">目前活動的匯入、追蹤與品牌月額度都在投放中心管理。</p>
      {advertisingHistory === "has_history" && (
        <div className="rounded-lg border border-border p-4 text-sm">
          <Link className="font-medium text-primary underline" to={`/brands/${encodeURIComponent(brandId)}/intake/history`}>回顧歷史投放（選用）</Link>
          <p className="mt-1 text-muted-foreground">歷史數字與素材供回顧、標記使用，不會加入投放中心的目前活動。</p>
        </div>
      )}
    </div>
  );
}

function ReadinessCard({ state }: { state: OptionalState<LaunchReadiness> }) {
  if (state.status === "loading") return <Skeleton className="h-24" />;
  if (state.status === "error") return null;
  const { data } = state;
  return (
    <div className="rounded-lg border border-border bg-card p-6 shadow-[var(--shadow-card)]">
      <h2 className="font-display text-lg text-foreground">可以開始投放了嗎</h2>
      <div className="mt-3">
        <ReadinessList readiness={data} />
      </div>
      <div className="mt-4 flex gap-3">
        <Button asChild>
          <Link to={data.primary.href}>{data.primary.label}</Link>
        </Button>
        {data.secondary && (
          <Button asChild variant="outline">
            <Link to={data.secondary.href}>{data.secondary.label}</Link>
          </Button>
        )}
      </div>
    </div>
  );
}

function PersonaProgress({ state }: { state: OptionalState<PersonaBundle> }) {
  if (state.status === "loading") return <Skeleton className="h-20" />;
  if (state.status === "error") return <p className="text-sm text-muted-foreground">人物誌狀態暫時讀不到，不影響你先前往品牌頁。</p>;
  if (state.data.generation.status === "running") {
    return (
      <div className="rounded-lg border border-dashed border-border bg-card p-5 text-sm text-muted-foreground">
        <p className="font-medium text-foreground">👥 人物誌產生中</p>
        <p className="mt-1">正在整理典型客人的樣子，好了會出現在收件匣。</p>
      </div>
    );
  }
  if (state.data.generation.status === "failed") {
    return <p className="text-sm text-muted-foreground">人物誌這次還沒整理好，不影響建檔完成；可稍後到顧客原話頁重試。</p>;
  }
  return <p className="text-sm text-muted-foreground">{state.data.personas.length > 0 ? "人物誌已整理好，可到顧客原話頁查看。" : "人物誌正在等待可用資料。"}</p>;
}
