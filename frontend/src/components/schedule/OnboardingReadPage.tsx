import { useEffect, useState, type ReactNode } from "react";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import {
  acceptOnboardingConclusions,
  fetchOnboardingRead,
  startOnboardingRead,
  type OnboardingJob,
  type OnboardingReadState,
} from "@/lib/onboardingReadApi";
import { ReadingConclusions } from "./ReadingConclusions";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: OnboardingReadState };

/** 開帳讀歷史（票 S2 D14）：讀一個品牌過去在 Meta 上投過的活動，逐活動各跑一個分析師，
 * 交人手動勾選要不要把結論存進學習帳本。頁面本身不做任何判斷——視窗、歸因窗、缺資料的
 * 日子全部是後端算好的既定事實（`app/schedule/onboarding.py` D6），這裡只負責顯示跟
 * 兩個動作（開始讀取／採用結論）。 */
export function OnboardingReadPage({ brandId }: { brandId: string }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [acceptingTaskId, setAcceptingTaskId] = useState<string | null>(null);
  const [acceptErrors, setAcceptErrors] = useState<Record<string, string>>({});

  function load() {
    setState({ status: "loading" });
    fetchOnboardingRead(brandId)
      .then((data) => {
        setState({ status: "ready", data });
        // 票 05-1 的既有理由同樣適用這裡：剛按下「開始讀取」那一刻，worker 可能還沒把
        // 第一列 llm_task 插進去，`starting` 要撐住輪詢直到 load() 真的看到伺服器狀態，
        // 才在這裡（唯一清它的地方）清掉——不在 POST 的 finally 清（見 SchedulePage.tsx
        // `:152-167` 的同一段註解）。
        setStarting(false);
      })
      .catch((err: unknown) =>
        setState({
          status: "error",
          message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。",
        }),
      );
  }

  useEffect(load, [brandId]);

  // 沒有「整個讀取還在跑」的單一旗標（後端的 `finished` 只代表『全部成功』，一個活動
  // 永久失敗也會讓 `finished` 停在 false，但那不是還在跑）——用逐一活動自己的 `running`
  // 判斷，跟本地「我剛按下去」旗標一起撐住輪詢，是 `SchedulePage.tsx:152-167` 同一個模式。
  const anyJobRunning =
    state.status === "ready" && Boolean(state.data.read?.jobs.some((j) => j.running));
  const runningNow = starting || anyJobRunning;
  useEffect(() => {
    if (!runningNow) return;
    const timer = setInterval(load, 2000);
    return () => clearInterval(timer);
  }, [runningNow, brandId]);

  async function handleStart() {
    setStarting(true);
    setStartError(null);
    try {
      const data = await startOnboardingRead(brandId);
      setState({ status: "ready", data });
    } catch (err) {
      setStartError(err instanceof Error ? err.message : "開始讀取失敗，請稍後再試。");
      setStarting(false); // 失敗（含 409）不會有後續輪詢清掉，這裡不清就永遠鎖住按鈕。
    }
  }

  async function handleAccept(taskId: string, indexes: number[]) {
    setAcceptingTaskId(taskId);
    setAcceptErrors((prev) => {
      const next = { ...prev };
      delete next[taskId];
      return next;
    });
    try {
      const data = await acceptOnboardingConclusions(brandId, taskId, indexes);
      setState({ status: "ready", data });
    } catch (err) {
      setAcceptErrors((prev) => ({
        ...prev,
        [taskId]: err instanceof Error ? err.message : "採用失敗，請稍後再試。",
      }));
    } finally {
      setAcceptingTaskId(null);
    }
  }

  let content: ReactNode;
  if (state.status === "loading") {
    content = (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 3 }, (_, i) => (
          <Skeleton key={i} className="h-12 w-full" />
        ))}
      </div>
    );
  } else if (state.status === "error") {
    content = (
      <EmptyState title="讀取失敗" description={state.message} onAction={load} actionLabel="重新載入" />
    );
  } else {
    const { data } = state;
    if (data.bound_accounts.length === 0) {
      // 誠實的空狀態（S2-DESIGN.md D14）：新品牌、沒綁過 Meta 廣告帳戶時就是這樣，
      // 不是錯誤，也不給一個按了會 400 的按鈕。
      content = (
        <EmptyState
          title="還沒有綁定 Meta 廣告帳戶"
          description="這個品牌還沒有綁定 Meta 廣告帳戶，請先到「Meta 廣告帳戶」頁綁定，才能讀取過去投過的活動。"
        />
      );
    } else if (data.read === null) {
      content = (
        <div className="rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)]">
          <p className="mb-3 text-sm text-muted-foreground">
            讀取這個品牌綁定帳戶過去在 Meta 上投過的活動，逐一分析結構、素材與逐日成效，
            交你勾選要不要把看出來的結論存進學習帳本。
          </p>
          {startError && <p className="mb-3 text-sm text-danger">{startError}</p>}
          <button
            type="button"
            onClick={handleStart}
            disabled={starting}
            className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {starting ? "開始讀取中…" : "開始讀取"}
          </button>
        </div>
      );
    } else {
      const { read } = data;
      content = (
        <div className="flex flex-col gap-4">
          <div className="rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)]">
            {read.window && (
              <p className="mb-1 text-sm text-foreground">
                讀到的時間窗：{read.window.since} 到 {read.window.until}
              </p>
            )}
            <p className="mb-1 text-sm text-foreground">
              歸因窗：{read.attribution_windows.length > 0 ? read.attribution_windows.join("、") : "（沒有資料）"}
            </p>
            {read.days_without_data.length > 0 && (
              <p className="mb-1 text-sm text-muted-foreground">
                完全沒有資料的日子：{read.days_without_data.join("、")}
                <br />
                {read.coverage_note}
              </p>
            )}
            <p className="mb-1 text-sm text-muted-foreground">{read.campaigns_note}</p>
            {/* 沒派人讀的活動要看得見，不是靜靜少掉（票 S2 §1／§5）。實測那個帳號
                58 個活動裡有 34 個屬於這類，數量大到不講就是在謊報涵蓋範圍。 */}
            {read.campaigns_without_numbers.length > 0 && (
              <p className="mb-1 text-sm text-muted-foreground">
                另外有 {read.campaigns_without_numbers.length} 個活動 Meta 還列得出來，但這段期間
                我們手上一列數字都沒有，所以沒有派人讀：
                {read.campaigns_without_numbers.map((c) => c.name || c.campaign_id).join("、")}
              </p>
            )}
            <p className="text-sm font-medium text-foreground">
              進度：{read.succeeded} / {read.expected} 個活動完成
            </p>
            {runningNow && (
              <p className="mt-2 text-sm text-muted-foreground">
                讀取中…可以先離開這一頁，回來會自己接上。
              </p>
            )}
          </div>

          {startError && <p className="text-sm text-danger">{startError}</p>}
          <button
            type="button"
            onClick={handleStart}
            disabled={starting || runningNow}
            className="self-start rounded-md border border-primary px-3 py-1.5 text-sm font-medium text-primary hover:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {starting ? "開始讀取中…" : "重新開始讀取"}
          </button>

          {read.jobs.map((job) => (
            <JobCard
              key={job.task_id}
              job={job}
              busy={acceptingTaskId === job.task_id}
              error={acceptErrors[job.task_id] ?? null}
              onAccept={handleAccept}
            />
          ))}
        </div>
      );
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <Breadcrumb items={[{ label: "跨品牌總覽", href: "/" }, { label: "開帳讀歷史" }]} />
      <h1 className="font-display text-2xl text-foreground">開帳讀歷史</h1>
      {content}
    </div>
  );
}

function JobCard({
  job,
  busy,
  error,
  onAccept,
}: {
  job: OnboardingJob;
  busy: boolean;
  error: string | null;
  onAccept: (taskId: string, indexes: number[]) => void;
}) {
  return (
    <div className="rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)]">
      <h2 className="mb-2 font-display text-lg text-foreground">
        {job.campaign_name || job.campaign_id}
      </h2>
      {job.running && <p className="text-sm text-muted-foreground">讀取中…</p>}
      {!job.running && job.failure && <p className="text-sm text-danger">{job.failure}</p>}
      {job.unreadable_ads.length > 0 && (
        <p className="mb-2 text-xs text-muted-foreground">
          Meta 現在回不出這幾則的素材：
          {job.unreadable_ads.map((ad) => ad.name || ad.ad_id).join("、")}
        </p>
      )}
      {!job.running && !job.failure && job.conclusions.length > 0 && (
        <ReadingConclusions
          taskId={job.task_id}
          conclusions={job.conclusions}
          onAccept={onAccept}
          busy={busy}
          error={error}
        />
      )}
    </div>
  );
}
