import { useEffect, useRef, useState } from "react";
import { EmptyState } from "@/components/layout/EmptyState";
import { Pager } from "@/components/layout/Pager";
import {
  archiveCustomerVoice,
  deleteCustomerVoice,
  fetchCustomerVoiceJob,
  TASK_LAYER_LABELS,
  type LibraryCustomerVoice,
  type LibraryCustomerVoiceJob,
} from "@/lib/libraryApi";
import { usePagination } from "@/lib/usePagination";
import { Badge } from "../shared/Badge";
import { InlineDeleteButton } from "../shared/InlineDeleteButton";
import { CustomerVoiceGuidePanel } from "../panels/CustomerVoiceGuidePanel";
import { CustomerVoicePanel } from "../panels/CustomerVoicePanel";
import { PersonaSection } from "../PersonaSection";

/** One extraction still running or failed. Only these two show; `done` is a stored voice and `unknown` shows nothing. */
interface PlaceholderJob {
  jobKey: string;
  status: { status: "running" } | { status: "failed"; message: string };
}

const JOB_FAILED_FALLBACK = "這段原話沒有讀完，請再試一次。";

/** The payload's jobs (F50-I07: newest per key, last 24 h, queued ones included) as placeholder rows. */
function placeholdersFrom(jobs: LibraryCustomerVoiceJob[]): PlaceholderJob[] {
  return jobs.flatMap((job): PlaceholderJob[] => {
    if (job.status === "running") return [{ jobKey: job.job_key, status: { status: "running" } }];
    if (job.status === "failed") {
      return [{ jobKey: job.job_key, status: { status: "failed", message: job.error ?? JOB_FAILED_FALLBACK } }];
    }
    return [];
  });
}

/** 顧客原話分頁（契約 S5.32–S5.42）：使用中／已封存兩段，貼入後背景抽取——送出即關側板，
 * 清單頂端出現「分析中」佔位卡，輪詢到完成／失敗前不鎖頁面（五鐵則③）。
 * F50-I16 (Contract J): the placeholder rows come from the library payload's `customer_voice_jobs`, so a reload keeps a
 * running or failed extraction; a just-submitted job joins them until the next read. A poll answer `unknown` (no job,
 * no AI call) removes the row instead of saying 「正在讀」 forever. */
export function CustomerVoiceTab({
  brandId,
  voices,
  jobs: servedJobs,
  onChanged,
}: {
  brandId: string;
  voices: LibraryCustomerVoice[];
  jobs: LibraryCustomerVoiceJob[];
  onChanged: () => void;
}) {
  const [newPanelOpen, setNewPanelOpen] = useState(false);
  const [guideOpen, setGuideOpen] = useState(false);
  const [jobs, setJobs] = useState<PlaceholderJob[]>(() => placeholdersFrom(servedJobs));
  const pollTimers = useRef<Record<string, ReturnType<typeof setInterval>>>({});

  // A changed payload replaces the served rows; a row submitted here and not served yet stays. Keyed on the content:
  // the parent passes a new array on every render.
  const servedKey = JSON.stringify(servedJobs);
  const firstServedKey = useRef(servedKey);
  useEffect(() => {
    if (servedKey === firstServedKey.current) return;
    firstServedKey.current = servedKey;
    const served: LibraryCustomerVoiceJob[] = JSON.parse(servedKey);
    const servedKeys = new Set(served.map((job) => job.job_key));
    setJobs((prev) => [...prev.filter((job) => !servedKeys.has(job.jobKey)), ...placeholdersFrom(served)]);
  }, [servedKey]);

  useEffect(() => {
    const timers = pollTimers.current;
    return () => {
      for (const jobKey of Object.keys(timers)) {
        clearInterval(timers[jobKey]);
        delete timers[jobKey];
      }
    };
  }, []);

  const runningKeys = jobs.filter((job) => job.status.status === "running").map((job) => job.jobKey).join(",");
  useEffect(() => {
    for (const jobKey of runningKeys ? runningKeys.split(",") : []) {
      if (!pollTimers.current[jobKey]) startPolling(jobKey);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- a key starts polling once; startPolling reads refs
  }, [runningKeys]);

  function startPolling(jobKey: string) {
    pollTimers.current[jobKey] = setInterval(async () => {
      let status;
      try {
        status = await fetchCustomerVoiceJob(brandId, jobKey);
      } catch {
        return; // 暫時查詢失敗，下一輪再試，不中斷輪詢。
      }
      if (status.status === "running") return;
      clearInterval(pollTimers.current[jobKey]);
      delete pollTimers.current[jobKey];
      if (status.status === "failed") {
        const failed: PlaceholderJob = { jobKey, status: { status: "failed", message: status.message } };
        setJobs((prev) => prev.map((j) => (j.jobKey === jobKey ? failed : j)));
        return;
      }
      setJobs((prev) => prev.filter((j) => j.jobKey !== jobKey));
      if (status.status === "done") onChanged();
    }, 1000);
  }

  function handleSubmitted(jobKey: string) {
    setJobs((prev) => [{ jobKey, status: { status: "running" } }, ...prev]);
  }

  function retryJob(jobKey: string) {
    setJobs((prev) => prev.filter((j) => j.jobKey !== jobKey));
    setNewPanelOpen(true);
  }

  const active = voices.filter((v) => v.status === "active");
  const archived = voices.filter((v) => v.status === "archived");
  const activePage = usePagination(active);
  const archivedPage = usePagination(archived);

  return (
    <div className="flex flex-col gap-6">
      <PersonaSection brandId={brandId} />
      <div className="flex items-center justify-between">
        <h2 className="font-display text-lg text-foreground">顧客原話</h2>
        <button
          type="button"
          onClick={() => setNewPanelOpen(true)}
          className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90"
        >
          貼入顧客原話
        </button>
      </div>

      <button
        type="button"
        onClick={() => setGuideOpen(true)}
        className="self-start text-sm text-primary underline-offset-4 hover:underline"
      >
        不知道去哪找顧客原話？看這裡的在地化指引 →
      </button>

      {jobs.length === 0 && active.length === 0 ? (
        <EmptyState
          title="這個品牌還沒有顧客原話"
          description="貼入評論、留言、客服對話，AI 會幫你抽出痛點與用語，讓 Hook 與文案有真實顧客聲音支撐。"
        />
      ) : (
        <div ref={activePage.topRef} className="flex flex-col gap-3">
          <ul className="flex flex-col gap-3">
            {jobs.map((job) => (
              <PlaceholderCard key={job.jobKey} job={job} onRetry={() => retryJob(job.jobKey)} />
            ))}
            {activePage.pageItems.map((voice) => (
              <VoiceCard
                key={voice.id}
                voice={voice}
                brandId={brandId}
                archived={false}
                onChanged={onChanged}
              />
            ))}
          </ul>
          <Pager
            page={activePage.page}
            pageCount={activePage.pageCount}
            totalCount={activePage.totalCount}
            onChange={activePage.goToPage}
          />
        </div>
      )}

      {archived.length > 0 && (
        <details className="flex flex-col gap-3">
          <summary className="cursor-pointer text-sm font-semibold text-foreground">
            已封存（{archived.length}）
          </summary>
          <div ref={archivedPage.topRef} className="mt-3 flex flex-col gap-3">
            <ul className="flex flex-col gap-3">
              {archivedPage.pageItems.map((voice) => (
                <VoiceCard key={voice.id} voice={voice} brandId={brandId} archived onChanged={onChanged} />
              ))}
            </ul>
            <Pager
              page={archivedPage.page}
              pageCount={archivedPage.pageCount}
              totalCount={archivedPage.totalCount}
              onChange={archivedPage.goToPage}
            />
          </div>
        </details>
      )}

      {newPanelOpen && (
        <CustomerVoicePanel
          brandId={brandId}
          onClose={() => setNewPanelOpen(false)}
          onSubmitted={handleSubmitted}
          onOpenGuide={() => setGuideOpen(true)}
        />
      )}
      {guideOpen && <CustomerVoiceGuidePanel onClose={() => setGuideOpen(false)} />}
    </div>
  );
}

function PlaceholderCard({ job, onRetry }: { job: PlaceholderJob; onRetry: () => void }) {
  if (job.status.status === "failed") {
    return (
      <li className="flex flex-col gap-2 rounded-md border border-danger/40 bg-danger/5 p-4 text-sm">
        <p className="text-danger">{job.status.message}</p>
        <div>
          <button
            type="button"
            onClick={onRetry}
            className="rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground hover:border-primary hover:text-primary"
          >
            重試
          </button>
        </div>
      </li>
    );
  }
  return (
    <li className="flex items-center gap-2 rounded-md border border-dashed border-border bg-muted/40 p-4 text-sm text-muted-foreground">
      <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-primary" aria-hidden="true" />
      AI 正在讀這段原話，可以先做別的事，等等收件匣會通知
    </li>
  );
}

function VoiceCard({
  voice,
  brandId,
  archived,
  onChanged,
}: {
  voice: LibraryCustomerVoice;
  brandId: string;
  archived: boolean;
  onChanged: () => void;
}) {
  return (
    <li className="flex flex-col gap-2 rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)]">
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge>{voice.source_channel_label}</Badge>
          {voice.source_detail && <span className="text-xs text-muted-foreground">{voice.source_detail}</span>}
        </div>
        <div className="flex shrink-0 items-center gap-3 text-xs">
          <button
            type="button"
            onClick={async () => {
              await archiveCustomerVoice(brandId, voice.id);
              onChanged();
            }}
            className="text-primary hover:underline"
          >
            {archived ? "恢復" : "封存"}
          </button>
          <InlineDeleteButton
            confirmText="確定要刪除這筆顧客原話？刪除後會記在稽核紀錄，但資料本身會消失。"
            onDelete={async () => {
              await deleteCustomerVoice(brandId, voice.id);
              onChanged();
            }}
          />
        </div>
      </div>

      <details className="text-xs text-muted-foreground">
        <summary className="cursor-pointer">原文全文</summary>
        <p className="mt-1 whitespace-pre-wrap">{voice.raw_text}</p>
      </details>

      {!archived &&
        (voice.extraction.length === 0 ? (
          <p className="text-xs text-muted-foreground">AI 沒有在這段原話裡找到值得引用的重點。</p>
        ) : (
          <div className="flex flex-col gap-2">
            {voice.extraction.map((item, i) => (
              <div key={i} className="rounded-md border border-border bg-muted/30 p-2.5 text-sm">
                <div className="mb-1 flex items-center gap-1.5">
                  <Badge>{TASK_LAYER_LABELS[item.task_layer]}</Badge>
                  {item.signal === "unprompted" && <Badge tone="success">主動提及</Badge>}
                </div>
                <p className="text-foreground">「{item.quote}」</p>
                <p className="mt-0.5 text-muted-foreground">{item.insight}</p>
              </div>
            ))}
          </div>
        ))}
    </li>
  );
}
