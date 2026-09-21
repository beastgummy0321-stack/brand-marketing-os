import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { Skeleton } from "@/components/layout/Skeleton";
import { cn } from "@/lib/utils";
import { formatCurrency } from "@/lib/format";
import type { CampaignCard as CampaignCardData } from "@/lib/adsApi";
import { getTarget, getTriage, type TriageClass, type TriageItem } from "@/lib/adsTriageApi";

type Basis = "own" | "break_even" | "trailing_30";
const BASIS_LABEL: Record<Basis, string> = { own: "自訂", break_even: "損益兩平", trailing_30: "近 30 天" };

/** 目標視圖的共同子集：不管是從 `triage.items[0].target`（`TriageTargetView`）還是
 * `getTarget()`（`CampaignTarget`）來的，卡片只用得到這四欄。 */
interface TargetView {
  value: number | null;
  basis: Basis | null;
  result_label: string;
  missing: string[];
}

type CardState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; items: TriageItem[]; target: TargetView };

const SEGMENTS: { cls: Exclude<TriageClass, "no_target">; label: string; swatch: string }[] = [
  { cls: "stop_loss", label: "停損", swatch: "bg-danger" },
  { cls: "worse", label: "變差", swatch: "bg-warning" },
  { cls: "better", label: "變好", swatch: "bg-success" },
  { cls: "flat", label: "持平", swatch: "bg-muted-foreground/40" },
  { cls: "insufficient", label: "資料不足", swatch: "bg-border" },
];

function chip(tone?: "warn") {
  return cn(
    "inline-flex w-fit shrink-0 items-center gap-1 rounded-full px-2.5 py-1 text-xs",
    tone === "warn" ? "bg-warning/10 text-warning" : "bg-muted text-muted-foreground",
  );
}

/** 五分類長條：寬度＝該分類則數／總則數；`no_target` 不算進任一色段（也不占五色之一），
 * 但仍算在分母裡（design-system 誠實空狀態——不假裝那幾則已經判斷過）。圖例只列非零分類。 */
function Strip({ items }: { items: TriageItem[] }) {
  const total = items.length;
  const counts: Record<Exclude<TriageClass, "no_target">, number> = {
    stop_loss: 0, worse: 0, better: 0, flat: 0, insufficient: 0,
  };
  for (const item of items) {
    if (item.class !== "no_target") counts[item.class]++;
  }
  const nonZero = SEGMENTS.filter((s) => counts[s.cls] > 0);
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex h-3.5 w-full overflow-hidden rounded-full bg-muted">
        {SEGMENTS.map((s) => (
          <div key={s.cls} className={s.swatch} style={{ width: `${(counts[s.cls] / total) * 100}%` }} />
        ))}
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {nonZero.map((s) => (
          <span key={s.cls} className="inline-flex items-center gap-1.5">
            <span aria-hidden="true" className={cn("inline-block size-2 rounded-sm", s.swatch)} />
            {s.label} {counts[s.cls]}
          </span>
        ))}
      </div>
    </div>
  );
}

/** 尚未設定目標：整條打斜紋（誠實的未知態，不是量測出來的 0），按鈕帶去設定目標頁。 */
function HatchedStrip() {
  return (
    <div
      aria-hidden="true"
      className="h-3.5 w-full rounded-full bg-muted"
      style={{
        backgroundImage:
          "repeating-linear-gradient(45deg, var(--color-border), var(--color-border) 4px, transparent 4px, transparent 8px)",
      }}
    />
  );
}

function TargetBody({ items, target, targetHref }: { items: TriageItem[]; target: TargetView; targetHref: string }) {
  const label = `目標每次${target.result_label}成本`;

  if (target.value === null) {
    return (
      <div className="flex flex-col gap-2">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="text-[20px] font-semibold text-muted-foreground">尚未設定</p>
        <HatchedStrip />
        <Button asChild size="sm" className="self-start">
          <Link to={targetHref}>設定目標，才開始判斷</Link>
        </Button>
        {target.missing.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {target.missing.map((m) => (
              <span key={m} className={chip()}>{m}</span>
            ))}
          </div>
        )}
      </div>
    );
  }

  const basisLabel = target.basis ? BASIS_LABEL[target.basis] : null;
  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs text-muted-foreground">{label}</p>
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="numeric text-[20px] font-semibold">{formatCurrency(target.value)}</span>
        {basisLabel && <span className={chip()}>{basisLabel}</span>}
        <Link to={targetHref} className="text-sm text-primary hover:underline">調整</Link>
      </div>
      {items.length === 0 ? <span className={chip()}>沒有廣告資料</span> : <Strip items={items} />}
    </div>
  );
}

/** 活動卡（F19-I04，v7 原型 `ccard`）：一張卡一個 Campaign，自己打 `getTriage` 拿這個
 * Campaign 的判斷分佈；沒有廣告的 Campaign（`items.length===0`）觸發不到判斷，改讀
 * `getTarget` 只為了目標大數字——每張卡最多兩支請求。 */
export function CampaignCard({ brandId, campaign }: { brandId: string; campaign: CampaignCardData }) {
  const [state, setState] = useState<CardState>({ status: "loading" });
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    (async () => {
      // ponytail: one triage call per card; add a brand-level summary endpoint when a brand has >10 campaigns
      const triage = await getTriage(brandId, campaign.id);
      const target: TargetView = triage.items.length > 0
        ? triage.items[0].target
        : await getTarget(brandId, campaign.id);
      if (!cancelled) setState({ status: "ready", items: triage.items, target });
    })().catch(() => { if (!cancelled) setState({ status: "error" }); });
    return () => { cancelled = true; };
  }, [brandId, campaign.id, reload]);

  const targetHref = `/brands/${brandId}/ads/campaigns/${campaign.id}/target`;
  const budgetTotal = campaign.budget_progress.total;

  return (
    <article className={cn("surface flex flex-col gap-3 p-5", state.status === "error" && "bg-muted")}>
      <div className="flex items-start justify-between gap-2">
        <h3 className="min-w-0 truncate text-[15px] font-semibold">
          <Link to={`/brands/${brandId}/ads/campaigns/${campaign.id}`} className="hover:text-primary hover:underline">
            {campaign.name}
          </Link>
        </h3>
        <span className={chip()}>
          {campaign.objective || "尚待確認"}
          {state.status === "ready" ? `・${state.items.length} 則` : ""}
        </span>
      </div>

      {state.status === "loading" && (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-3.5 w-20" />
          <Skeleton className="h-6 w-32" />
          <Skeleton className="h-3.5 w-full rounded-full" />
        </div>
      )}

      {state.status === "error" && (
        <div className="flex flex-col gap-2">
          <p className="text-[15px] font-semibold text-muted-foreground">暫時讀取不到</p>
          {/* aria-label 帶活動名稱：頁面上每張卡都會印「重新讀取」，用 aria-label 讓螢幕
             閱讀器分得出這顆按鈕重試的是哪一張卡（其餘元件的重試各自有自己的可及名稱）。 */}
          <Button
            variant="outline"
            size="sm"
            className="self-start"
            aria-label={`重新讀取「${campaign.name}」`}
            onClick={() => setReload((v) => v + 1)}
          >
            重新讀取
          </Button>
        </div>
      )}

      {state.status === "ready" && (
        <TargetBody items={state.items} target={state.target} targetHref={targetHref} />
      )}

      {state.status !== "error" && (
        <div className="flex flex-wrap items-center gap-2">
          {budgetTotal !== null ? (
            <span className={chip()}>{formatCurrency(budgetTotal)}</span>
          ) : (
            <span className={chip("warn")}>預算待核實</span>
          )}
        </div>
      )}
    </article>
  );
}
