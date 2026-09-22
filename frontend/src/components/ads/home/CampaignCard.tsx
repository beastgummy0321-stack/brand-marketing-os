import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Badge } from "@/components/layout/ui/badge";
import { Button } from "@/components/layout/ui/button";
import { Skeleton } from "@/components/layout/Skeleton";
import { cn } from "@/lib/utils";
import { Chip } from "../patterns";
import { formatCurrency } from "@/lib/format";
import type { CampaignCard as CampaignCardData, CampaignSyncState } from "@/lib/adsApi";
import { getTriage, type TriageClass, type TriageData, type TriageItem } from "@/lib/adsTriageApi";
import { syncCampaign, syncJob } from "@/lib/adsExternalApi";
import { STATUS_LABEL, STATUS_TONE } from "./status";

type Basis = "own" | "break_even" | "trailing_30";
const BASIS_LABEL: Record<Basis, string> = { own: "自訂", break_even: "損益兩平", trailing_30: "近 30 天" };

/** 目標視圖：直接沿用 `TriageItem.target`（`TriageTargetView`）的形狀——campaign 沒有廣告時
 * (`items.length===0`) 這張卡完全不顯示目標（review 裁決 #2），所以不再需要另外打
 * `getTarget()` 湊一份備用視圖，一支 `getTriage` 打完就夠。 */
type TargetView = TriageItem["target"];

type CardState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; items: TriageItem[]; data?: TriageData };

const SEGMENTS: { cls: Exclude<TriageClass, "no_target">; label: string; swatch: string }[] = [
  { cls: "stop_loss", label: "停損", swatch: "bg-danger" },
  { cls: "worse", label: "變差", swatch: "bg-warning" },
  { cls: "better", label: "變好", swatch: "bg-success" },
  { cls: "flat", label: "持平", swatch: "bg-muted-foreground/40" },
  { cls: "insufficient", label: "資料不足", swatch: "bg-border" },
];

/** 目標／成本數字：後端不回幣別，`formatCurrency` 又是寫死 NT$——套在可能來自非台幣帳戶的
 * 數字上是錯的標籤（design-system §7、review 裁決）。v7 原型也只印數字本身（「450」），這裡
 * 照樣不印符號，只留千分位＋等寬數字。`trailing_30` 依據是 spend/result_count 現算出來的，
 * 常是小數（例如 5200/15＝346.67）——不用 `Math.round`，最多留兩位小數，3.1 還是印 3.1，不
 * 印成 3。金額類的總預算不受影響，那是系統自己算的 TWD 整數，繼續用 `formatCurrency`。 */
function formatPlainNumber(value: number): string {
  return value.toLocaleString("zh-TW", { maximumFractionDigits: 2 });
}

/** 五分類長條：分母是「真的判斷出五類之一」的則數，不含 `no_target`（review 裁決——
 * `no_target` 算在分母會讓長條永遠填不滿，也不代表「已判斷但持平」）。呼叫端算完 `no_target`
 * 另外印一顆「N 則無法判斷」的 chip，不混進這條色段。圖例只列非零分類。 */
function Strip({ counts, total }: { counts: Record<Exclude<TriageClass, "no_target">, number>; total: number }) {
  const nonZero = SEGMENTS.filter((s) => counts[s.cls] > 0);
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex h-3.5 w-full overflow-hidden rounded-full bg-muted">
        {SEGMENTS.map((s) => (
          <div
            key={s.cls}
            data-segment={s.cls}
            className={s.swatch}
            style={{ width: `${(counts[s.cls] / total) * 100}%` }}
          />
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

/** 尚未設定目標／讀取失敗共用：整條打斜紋（誠實的未知態，不是量測出來的 0）。 */
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

const REASON_CODE_LABEL: Record<string, string> = {
  below_sample_gate: "樣本還不夠",
  no_previous_window: "缺前一期可比資料",
  result_unknown_days: "成果數未知",
};

/** 「資料不足，先不判斷」卡片的 chip 文案（F24 Feature Decisions "Home card state"）：
 * 缺同步天數 > 還沒同步過成效 > 這批 insufficient 廣告裡最多的 reason_code。 */
function insufficientChip(data: TriageData, items: TriageItem[]): string {
  if (data.missing_days.length > 0) return `缺 ${data.missing_days.length} 天資料`;
  if (data.coverage === null) return "尚未同步成效";
  const counts = new Map<string, number>();
  for (const item of items) {
    if (item.class !== "insufficient") continue;
    counts.set(item.reason_code, (counts.get(item.reason_code) ?? 0) + 1);
  }
  let dominant: string | null = null;
  let max = 0;
  for (const [code, count] of counts) {
    if (count > max) { max = count; dominant = code; }
  }
  return (dominant && REASON_CODE_LABEL[dominant]) || "資料不足";
}

/** 灰卡（prototype ccard `state:"failed"`，F24 擴充到 `syncing`／`disconnected`）：同一張灰卡、
 * 同一句「暫時讀取不到」與打斜紋，只有 chip 文案跟按鈕依 `sync.state` 換（Feature Decisions
 * "Home card state"）。`disconnected` 沒有「重新讀取」能修的東西——去連接頁才對。 */
function SyncAbnormalBody({
  sync, campaignName, connectionsHref, retrying, onRetry,
}: { sync: CampaignSyncState; campaignName: string; connectionsHref: string; retrying: boolean; onRetry: () => void }) {
  return (
    <div className="flex flex-col gap-2">
      <p className="text-[15px] font-semibold text-muted-foreground">暫時讀取不到</p>
      <HatchedStrip />
      <div className="flex flex-wrap items-center gap-2">
        <Chip>
          {sync.state === "syncing" ? "讀取中" : sync.state === "disconnected" ? "廣告帳戶未連接" : "已保存的紀錄都還在"}
        </Chip>
        {sync.state === "disconnected" ? (
          <Button asChild variant="outline" size="sm">
            <Link to={connectionsHref}>去連接</Link>
          </Button>
        ) : (
          <Button
            variant="outline"
            size="sm"
            aria-label={`重新讀取「${campaignName}」`}
            disabled={sync.state === "syncing" || retrying}
            onClick={onRetry}
          >
            重新讀取
          </Button>
        )}
      </div>
    </div>
  );
}

/** Warn 卡（prototype ccard `state:"waiting"`）：「資料不足，先不判斷」，按鈕一律去等待頁
 * （F24-I03 `wait()`，這裡只給連結）。 */
function InsufficientBody({ data, items, waitHref }: { data: TriageData; items: TriageItem[]; waitHref: string }) {
  return (
    <div className="flex flex-col gap-2">
      <p className="text-[15px] font-semibold text-warning">資料不足，先不判斷</p>
      <HatchedStrip />
      <div className="flex flex-wrap items-center gap-2">
        <Chip tone="warn">{insufficientChip(data, items)}</Chip>
        <Button asChild variant="outline" size="sm">
          <Link to={waitHref}>去處理</Link>
        </Button>
      </div>
    </div>
  );
}

function TargetBody({
  items, targetHref, workspaceHref,
}: { items: TriageItem[]; targetHref: string; workspaceHref: string }) {
  // 沒有可判讀的廣告（草稿／待發布／剛同步）：不會判斷，催著設目標也沒用——設了也沒有廣告可以
  // 套。唯一的動作是進去活動本身看狀況（review 裁決 #2）。
  if (items.length === 0) {
    return (
      <div className="flex flex-col gap-2">
        <Chip>沒有廣告資料</Chip>
        <Link to={workspaceHref} className="w-fit text-sm text-muted-foreground hover:text-primary hover:underline">
          進入活動 ›
        </Link>
      </div>
    );
  }

  const target: TargetView = items[0].target;
  const label = `目標每次${target.result_label}成本`;
  const known: Record<Exclude<TriageClass, "no_target">, number> = {
    stop_loss: 0, worse: 0, better: 0, flat: 0, insufficient: 0,
  };
  let noTargetCount = 0;
  for (const item of items) {
    if (item.class === "no_target") noTargetCount++;
    else known[item.class]++;
  }
  const knownTotal = items.length - noTargetCount;

  if (target.value === null) {
    return (
      <div className="flex flex-col gap-2">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="text-[20px] font-semibold text-muted-foreground">尚未設定</p>
        <HatchedStrip />
        {/* 頁面已有自己的主要動作（建立投放計畫），這顆是次要按鈕，不搶主按鈕的視覺份量
           （review 裁決）。 */}
        <Button asChild variant="outline" size="sm" className="self-start">
          <Link to={targetHref}>設定目標，才開始判斷</Link>
        </Button>
        {target.missing.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {target.missing.map((m) => (
              <Chip key={m}>{m}</Chip>
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
        <span className="numeric text-[20px] font-semibold">{formatPlainNumber(target.value)}</span>
        {basisLabel && <Chip>{basisLabel}</Chip>}
        <Link to={targetHref} className="text-sm text-primary hover:underline">調整</Link>
      </div>
      {knownTotal > 0 && <Strip counts={known} total={knownTotal} />}
      {noTargetCount > 0 && <Chip>{noTargetCount} 則無法判斷</Chip>}
    </div>
  );
}

/** 活動卡（F19-I04，v7 原型 `ccard`；review 裁決修正版）：一張卡一個 Campaign，自己打
 * `getTriage` 拿這個 Campaign 的判斷分佈。狀態（草稿／待發布／已結束）與匯入標記不是 triage
 * 的事，直接從 `campaign` 讀，跟讀取狀態無關，隨時看得到。 */
export function CampaignCard({ brandId, campaign }: { brandId: string; campaign: CampaignCardData }) {
  const [state, setState] = useState<CardState>({ status: "loading" });
  const [reload, setReload] = useState(0);
  // F24-I02：這張卡自己觸發的真同步（跟 `sync.state==="syncing"` 是兩件事——那是後端已經在
  // 跑的別的工作；這個 flag 是「這次按下重新讀取還沒收到終態」），避免使用者連點造成重複
  // 送出。同步 job 收斂後才 `setReload`，觸發下面的 effect 重打一次 `getTriage`（拿最新的
  // `data.sync`／`coverage`／`missing_days`，不必額外再打一支 campaign 清單）。
  const [retrying, setRetrying] = useState(false);
  const [syncJobId, setSyncJobId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    // ponytail: one triage call per card; add a brand-level summary endpoint when a brand has >10 campaigns
    getTriage(brandId, campaign.id)
      .then((triage) => { if (!cancelled) setState({ status: "ready", items: triage.items, data: triage.data }); })
      .catch(() => { if (!cancelled) setState({ status: "error" }); });
    return () => { cancelled = true; };
  }, [brandId, campaign.id, reload]);

  // F24-I02「重新讀取」（sync 失敗／never 之外的真實失敗態）＝既有的 `syncCampaign` helper
  // （預設 body `{}`，30 天涵蓋 28 天判斷窗），送出後輪詢 `GET .../sync-jobs/:id` 直到
  // `status` 離開 pending/running，再重讀這張卡（Feature Decisions "Home card state"）。
  async function retrySync() {
    if (retrying) return;
    setRetrying(true);
    try {
      const result = await syncCampaign(brandId, campaign.id);
      setSyncJobId(result.job.id);
    } catch {
      setRetrying(false);
    }
  }

  useEffect(() => {
    if (!syncJobId) return;
    const jobId = syncJobId; // narrow to `string` for the `poll` closure below
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const result = await syncJob(brandId, jobId);
        if (cancelled) return;
        if (result.job.status === "pending" || result.job.status === "running") {
          timer = setTimeout(() => void poll(), 3000);
        } else {
          setSyncJobId(null);
          setRetrying(false);
          setReload((v) => v + 1);
        }
      } catch {
        if (!cancelled) { setSyncJobId(null); setRetrying(false); }
      }
    }
    void poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [syncJobId, brandId]);

  const workspaceHref = `/brands/${brandId}/ads/campaigns/${campaign.id}`;
  // F20-I02：卡片名稱現在落在新的活動詳情頁（v7 `campPage()`），不是五分頁工作區——
  // 工作區網址不變，由詳情頁的「全部資料 ›」進去。「沒有廣告資料」時的「進入活動」連結
  // 仍照舊指向工作區（那個空狀態本身就是工作區才有意義的路，跟詳情頁重複沒有新資訊）。
  const detailHref = `${workspaceHref}/detail`;
  const targetHref = `${workspaceHref}/target`;
  const waitHref = `${workspaceHref}/wait`;
  const connectionsHref = `/brands/${brandId}/ads/connections`;
  const isError = state.status === "error";

  // F24-I02：sync 失敗／帳戶未連接（灰卡）跟「資料不足，先不判斷」（warn 卡）都是「triage 讀
  // 成功了，但這批數字不能信」——跟 `isError`（triage 這支 API 本身打不到）是不同的事實來源，
  // 「Triage request failure keeps today's error state」（Feature Decisions），所以只在
  // `state.status==="ready"` 時才看 `data.sync`／`missing_days`。缺 `data`（手寫測試 fixture
  // 沒補、do_not_touch 衝突見 `adsApi.ts` 註解）視同 `"never"`，走今天原本那張卡。
  const items = state.status === "ready" ? state.items : [];
  const triageData = state.status === "ready" ? state.data : undefined;
  const sync: CampaignSyncState = triageData?.sync ?? { state: "never", error: null, last_success_at: null };
  const isSyncAbnormal = state.status === "ready"
    && (sync.state === "failed" || sync.state === "syncing" || sync.state === "disconnected");
  // `!!triageData` 一起判斷：沒有 `data`（手寫 fixture 沒補、視同 "never"）不能只靠
  // `items.every(insufficient)` 就判定資料不足，否則下面渲染會因為拿不到 `triageData` 而
  // 整段空白——沒有 `data` 一律照今天的卡（review 自我檢查）。
  const isInsufficient = state.status === "ready" && !isSyncAbnormal && !!triageData
    && ((items.length > 0 && items.every((i) => i.class === "insufficient"))
      || triageData.missing_days.length > 0);

  const statusLabel = campaign.origin === "imported" ? "平台活動" : STATUS_LABEL[campaign.status];
  const statusTone = STATUS_TONE[campaign.status];

  // 預算：站內 Campaign 讀自己算好的總預算（`budget_progress.total`）；匯入的平台活動這支卡
  // 目前沒有平台原生預算可讀（那在 `NativeEntity.budget_amount`，另一支 API），照舊卡的作法只
  // 標「平台預算」，不是留白也不是編數字（review 裁決）。金額一律帶著「總預算」這個標籤，不
  // 印一個沒人知道是什麼的裸數字。
  const budgetTotal = campaign.budget_progress.total;
  const budgetChip = campaign.origin === "imported"
    ? <Chip>平台預算</Chip>
    : budgetTotal !== null
      ? <Chip>總預算 {formatCurrency(budgetTotal)}</Chip>
      : <Chip tone="warn">預算待核實</Chip>;

  return (
    <article
      className={cn(
        // `.surface`（tokens.css，unlayered）比 Tailwind utilities 層的 `bg-muted` 優先權高，
        // `cn()` 疊上去蓋不掉——讀取失敗態乾脆不套 `.surface`，直接用同樣的邊框／圓角／背景
        // 工具類組出來（review 裁決）。isSyncAbnormal（prototype `state:"failed"`）套同一張
        // 灰卡；isInsufficient（`state:"waiting"`）維持白底（prototype 只有 failed 是灰的）。
        isError || isSyncAbnormal ? "min-w-0 rounded-xl border border-border bg-muted" : "surface",
        "flex flex-col gap-3 p-5",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="min-w-0 flex-1 text-[15px] font-semibold">
          {/* h3／連結本身是 flex row：長名稱只讓名稱那格 truncate，「›」永遠是 shrink-0、
             不被擠掉（review 裁決）；整個 <Link> 還是同一個點擊區域。 */}
          <Link to={detailHref} className="flex min-w-0 items-center gap-0.5 hover:text-primary hover:underline">
            <span className="min-w-0 truncate" title={campaign.name}>{campaign.name}</span>
            {/* aria-hidden：只是「這裡可以點」的視覺提示，不進可及名稱——名稱連結要留純活動
               名稱給 e2e／accessible name 用（review 裁決）。 */}
            <span aria-hidden="true" className="shrink-0 text-muted-foreground">›</span>
          </Link>
        </h3>
        <div className="flex shrink-0 items-center gap-1.5">
          <Badge variant={statusTone}>{statusLabel}</Badge>
          {/* Imported campaigns carry a whole sentence as objective: only the objective text
             truncates, the ad count never does, and the campaign name keeps its room. */}
          <Chip className="max-w-[14rem] items-center">
            <span className="min-w-0 truncate" title={campaign.objective || undefined}>
              {campaign.objective || "尚待確認"}
            </span>
            {state.status === "ready" && <span className="shrink-0">・{state.items.length} 則</span>}
          </Chip>
        </div>
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
          <HatchedStrip />
          <div className="flex flex-wrap items-center gap-2">
            {/* 讀取失敗只是這次沒拿到新的判斷結果，已經存的紀錄沒有被動過——這句話對這個
               失敗態一定為真才印（review 裁決）。 */}
            <Chip>已保存的紀錄都還在</Chip>
            {/* aria-label 帶活動名稱：頁面上每張卡都會印「重新讀取」，用 aria-label 讓螢幕
               閱讀器分得出這顆按鈕重試的是哪一張卡（其餘元件的重試各自有自己的可及名稱）。 */}
            <Button
              variant="outline"
              size="sm"
              aria-label={`重新讀取「${campaign.name}」`}
              onClick={() => setReload((v) => v + 1)}
            >
              重新讀取
            </Button>
          </div>
        </div>
      )}

      {state.status === "ready" && isSyncAbnormal && (
        <SyncAbnormalBody
          sync={sync}
          campaignName={campaign.name}
          connectionsHref={connectionsHref}
          retrying={retrying}
          onRetry={() => void retrySync()}
        />
      )}

      {state.status === "ready" && !isSyncAbnormal && isInsufficient && triageData && (
        <InsufficientBody data={triageData} items={items} waitHref={waitHref} />
      )}

      {state.status === "ready" && !isSyncAbnormal && !isInsufficient && (
        <TargetBody items={items} targetHref={targetHref} workspaceHref={workspaceHref} />
      )}

      {/* 預算來自 Campaign 清單本身，不是這張卡的 triage 讀取——讀取失敗也照樣看得到
         （review 裁決）。新的 sync 灰卡／資料不足 warn 卡照 prototype `ccard` 的 state 分支不
         印這列（那個分支從來沒帶預算 chip），只有既有的 `isError`／`ready` 卡維持原樣。 */}
      {!isSyncAbnormal && !isInsufficient && (
        <div className="flex flex-wrap items-center gap-2">{budgetChip}</div>
      )}
    </article>
  );
}
