import { useEffect, useRef, useState, type ReactNode } from "react";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import {
  acceptOnboardingConclusions,
  fetchOnboardingRead,
  retryOnboardingCampaign,
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
  /** 正在重讀的那一個活動，存的是**舊那一列**的 task_id：後端重派之後會多寫一列，那個
   * 活動的卡片就換成新的一列（後端只回每個活動最後一次嘗試），舊 task_id 從 `jobs` 裡
   * 消失就是「新的一次真的開始了」的信號。跟 `awaitedReadIdRef` 同一個理由用 ref：
   * `setInterval` 抓住的是舊閉包，ref 讀到的永遠是當下的。 */
  const retryingTaskIdRef = useRef<string | null>(null);
  const [retryingTaskId, setRetryingTaskId] = useState<string | null>(null);
  const [retryErrors, setRetryErrors] = useState<Record<string, string>>({});
  /** 「我剛按下去的那一次讀取」的 read_id；`"pending"` 是 POST 還在路上、還不知道 id
   * （那支端點會同步打一次 Meta Graph 列活動，真帳號要好幾秒，輪詢一定會插在中間跑）；
   * `null` 是沒有在等任何一次（一般瀏覽）。用 ref 不用 state：`load()` 每次 render 都是
   * 新的閉包，`setInterval` 抓住的那一份讀到的會是舊值，ref 讀到的永遠是當下的。 */
  const awaitedReadIdRef = useRef<string | null>(null);

  /** `silent`：輪詢用。**輪詢絕不可以把畫面打回 loading**（2026-08-31 真瀏覽器驗收抓到）
   * ——原本 `load()` 開頭無條件 `setState({ status: "loading" })`，讀取進行中每 2 秒一次
   * 的輪詢就把整頁換成三條骨架屏、拿到資料再換回來，畫面每 2 秒閃一次，捲動位置與展開
   * 狀態一起跳掉。骨架屏是給「畫面上還沒有東西」用的，不是給「正在拿新的一份」用的。
   *
   * 同一個理由，silent 模式失敗時不把已經在畫面上的資料換成錯誤頁：一次 40 分鐘的讀取
   * 中間掉一個封包，不該讓人已經讀到一半的結論整片消失。畫面上還沒有東西時才報錯。 */
  /** 重讀的那一次真的開始了嗎——舊 task_id 還在 `jobs` 裡就代表 worker 還沒寫新的一列，
   * 這時候不能清旗標，清了輪詢會停在「什麼都沒發生」的畫面上（跟 `starting` 同一種坑）。 */
  function noteRetryStarted(data: OnboardingReadState) {
    const waiting = retryingTaskIdRef.current;
    if (waiting !== null && !(data.read?.jobs ?? []).some((job) => job.task_id === waiting)) {
      retryingTaskIdRef.current = null;
      setRetryingTaskId(null);
    }
  }

  function load(silent = false) {
    if (!silent) setState({ status: "loading" });
    fetchOnboardingRead(brandId)
      .then((data) => {
        const awaited = awaitedReadIdRef.current;
        if (awaited !== null && data.read?.read_id !== awaited) {
          // 伺服器還在回**上一次**那份讀取：新讀取的第一列 `llm_task` 要等 worker 真的
          // 開始跑第一個活動才寫得進去，而 GET 是拿「最新有列的讀取」回答的（真帳號實測
          // 這個空窗是 9 秒：POST 07:55:59、第一列 07:56:08）。這一份不能拿來覆蓋畫面上
          // 剛開始的那一次——覆蓋下去，畫面就從「0 / 24 讀取中」跳回上一次的「24 / 24
          // 完成」，看起來像按了沒反應，而且輪詢會就此停住。
          //
          // 這正是 ADR 0042 那條「用工作項自己找列，不是用『最新』找列」在畫面這一層的
          // 樣子：我等的是**我按下去的那一次**，不是「伺服器現在覺得最新的那一次」。
          // 直接 return，`starting` 不清、輪詢繼續，等到伺服器認得這一次為止。
          return;
        }
        awaitedReadIdRef.current = null;
        noteRetryStarted(data);
        setState({ status: "ready", data });
        // 票 05-1 的既有理由同樣適用這裡：剛按下「開始讀取」那一刻，worker 可能還沒把
        // 第一列 llm_task 插進去，`starting` 要撐住輪詢直到 load() 真的看到伺服器狀態，
        // 才在這裡（唯一清它的地方）清掉——不在 POST 的 finally 清（見 SchedulePage.tsx
        // `:152-167` 的同一段註解）。
        setStarting(false);
      })
      .catch((err: unknown) =>
        setState((prev) =>
          silent && prev.status === "ready"
            ? prev
            : {
                status: "error",
                message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。",
              },
        ),
      );
  }

  useEffect(() => {
    load();
  }, [brandId]);

  // 沒有「整個讀取還在跑」的單一旗標（後端的 `finished` 只代表『全部成功』，一個活動
  // 永久失敗也會讓 `finished` 停在 false，但那不是還在跑）——用逐一活動自己的 `running`
  // 判斷，是 `SchedulePage.tsx:152-167` 同一個模式。
  //
  // **外加「還有活動連第一列都還沒寫進去」**（2026-08-31 真瀏覽器驗收抓到）：`llm_task`
  // 那幾列是 worker 真的開始跑某個活動時才寫的，所以剛派完工作的那幾秒，`jobs` 是空的、
  // 沒有任何一個 `running`。原本只靠本地 `starting` 旗標撐住，而 `starting` 在**第一次**
  // 輪詢回來就被清掉——那一次回來如果剛好還沒有任何一列，輪詢就此停住，畫面停在 0 / 24
  // 不再動，看起來像沒反應。`jobs.length < expected` 是伺服器講的事實，不是本地猜測；
  // 正常路徑會自己終止：24 列都寫進去、沒有一個在跑，它就是 false（有活動永久失敗也一樣，
  // 不會像 `finished` 那樣永遠輪詢下去）。
  //
  // ponytail: 例外是「job 在 `gateway.run_task()` 寫進第一列之前就死掉」（Graph 認證掛了、
  // 借不到連線——`app/schedule/onboarding.py` `_read_rows()` 的 ponytail 記的是同一個缺口）：
  // 那一列永遠不會出現，這個條件、以及上面 `awaitedReadIdRef` 那條等待，都不會自己收斂，
  // 分頁會每 2 秒打一次 API 停不下來、按鈕一直停在「開始讀取中…」。上限就是這個。升級路徑
  // 是後端把「佇列裡還剩幾個 job」一起報出來（procrastinate 知道，API 現在沒講），有了那個
  // 數字才分得出「還沒開始」跟「永遠不會開始」。真的被咬到再做——今天沒有那個數字，硬訂一個
  // 逾時秒數就是憑空發明一個沒有來源的常數。
  const read = state.status === "ready" ? state.data.read : null;
  const anyJobRunning = Boolean(read?.jobs.some((j) => j.running));
  const anyJobNotStartedYet = read !== null && read.jobs.length < read.expected;
  const runningNow =
    starting || anyJobRunning || anyJobNotStartedYet || retryingTaskId !== null;
  useEffect(() => {
    if (!runningNow) return;
    const timer = setInterval(() => load(true), 2000);
    return () => clearInterval(timer);
  }, [runningNow, brandId]);

  async function handleStart() {
    setStarting(true);
    setStartError(null);
    // POST 還沒回來之前就先擋住輪詢覆蓋畫面——這支端點會同步列一次 Meta 的活動，真帳號
    // 上要好幾秒，2 秒一次的輪詢一定會插在中間跑完並蓋掉狀態。
    awaitedReadIdRef.current = "pending";
    try {
      const data = await startOnboardingRead(brandId);
      awaitedReadIdRef.current = data.read?.read_id ?? null;
      setState({ status: "ready", data });
    } catch (err) {
      awaitedReadIdRef.current = null;
      setStartError(err instanceof Error ? err.message : "開始讀取失敗，請稍後再試。");
      setStarting(false); // 失敗（含 409）不會有後續輪詢清掉，這裡不清就永遠鎖住按鈕。
    }
  }

  /** 只重讀這一個活動：整批重跑是 24 次代理呼叫、12 分鐘，一個活動掉了不該付那個價錢。 */
  async function handleRetry(taskId: string) {
    retryingTaskIdRef.current = taskId;
    setRetryingTaskId(taskId);
    setRetryErrors((prev) => {
      const next = { ...prev };
      delete next[taskId];
      return next;
    });
    try {
      const data = await retryOnboardingCampaign(brandId, taskId);
      noteRetryStarted(data);
      setState({ status: "ready", data });
    } catch (err) {
      retryingTaskIdRef.current = null;
      setRetryingTaskId(null); // 失敗（含 409）不會有後續輪詢清掉，這裡不清就永遠鎖住按鈕。
      setRetryErrors((prev) => ({
        ...prev,
        [taskId]: err instanceof Error ? err.message : "重讀失敗，請稍後再試。",
      }));
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
      // `() => load()` 不是 `load`：直接傳函式，點擊事件會變成第一個參數，`silent` 就
      // 被當成 true——人按「重新載入」時反而不顯示骨架屏，看起來像沒反應。
      <EmptyState title="讀取失敗" description={state.message} onAction={() => load()} actionLabel="重新載入" />
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
              onRetry={handleRetry}
              retrying={retryingTaskId === job.task_id}
              retryError={retryErrors[job.task_id] ?? null}
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
      {/* 品牌設定缺一角時，外殼會安靜地少做事（沒有產品可以指名、挑不出成交最高的那天）。
          少做可以，不講不行——後端把同一份文字同時給模型跟這裡（`_setup_gaps()`），所以
          畫面上這幾句跟分析師讀到的逐字相同。放在最上面、三種狀態都顯示：還沒綁帳戶、
          還沒讀過的時候補設定最划算。 */}
      {state.status === "ready" && state.data.setup_gaps.length > 0 && (
        <div className="rounded-md border border-border bg-card p-4 text-sm shadow-[var(--shadow-card)]">
          <p className="mb-2 font-medium text-foreground">
            這個品牌有設定還沒補，所以這次讀取有幾件事我做不了：
          </p>
          <ul className="flex list-disc flex-col gap-1 pl-5 text-muted-foreground">
            {state.data.setup_gaps.map((gap) => (
              <li key={gap}>{gap}</li>
            ))}
          </ul>
        </div>
      )}
      {content}
    </div>
  );
}

function JobCard({
  job,
  busy,
  error,
  onAccept,
  onRetry,
  retrying,
  retryError,
}: {
  job: OnboardingJob;
  busy: boolean;
  error: string | null;
  onAccept: (taskId: string, indexes: number[]) => void;
  onRetry: (taskId: string) => void;
  retrying: boolean;
  retryError: string | null;
}) {
  return (
    <div className="rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)]">
      <h2 className="mb-2 font-display text-lg text-foreground">
        {job.campaign_name || job.campaign_id}
      </h2>
      {job.running && <p className="text-sm text-muted-foreground">讀取中…</p>}
      {/* 失敗的活動給一顆自己的重讀鍵：真跑量到 1/24 的分析師會漏掉結尾那塊 JSON，
          為了一個活動整批重跑是 24 次代理呼叫、12 分鐘。按下去只重派這一個。 */}
      {!job.running && job.failure && (
        <div className="flex flex-col items-start gap-2">
          <p className="text-sm text-danger">{job.failure}</p>
          {retryError && <p className="text-sm text-danger">{retryError}</p>}
          <button
            type="button"
            onClick={() => onRetry(job.task_id)}
            disabled={retrying}
            className="rounded-md border border-primary px-3 py-1.5 text-sm font-medium text-primary hover:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {retrying ? "重讀中…" : "重讀這一個活動"}
          </button>
        </div>
      )}
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
