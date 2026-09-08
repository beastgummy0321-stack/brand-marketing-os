import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { Skeleton } from "@/components/layout/Skeleton";
import { fetchPersonas, fetchTruthCard, type PersonaBundle, type TruthCard } from "@/lib/intakeT2Api";

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

  function load() {
    setTruth({ status: "loading" });
    setPersonas({ status: "loading" });
    fetchTruthCard(brandId)
      .then((data) => setTruth({ status: "ready", data }))
      .catch((err: unknown) => setTruth({ status: "error", message: err instanceof Error ? err.message : "讀取完成結果失敗。" }));
    fetchPersonas(brandId)
      .then((data) => setPersonas({ status: "ready", data }))
      .catch((err: unknown) => setPersonas({ status: "error", message: err instanceof Error ? err.message : "讀取人物誌狀態失敗。" }));
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
      <PersonaProgress state={personas} />
      <div className="flex gap-3">
        <Link to={"/brands/" + encodeURIComponent(brandId)} className="inline-flex rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90">前往品牌頁</Link>
        <Button type="button" variant="outline" onClick={onRestart}>再跑一次調研</Button>
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
