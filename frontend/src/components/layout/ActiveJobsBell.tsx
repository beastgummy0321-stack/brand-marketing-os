import { Bell } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { ACTIVE_JOB_KIND_LABELS, fetchActiveJobs, type ActiveJob } from "@/lib/jobsApi";
import { cn } from "@/lib/utils";

const POLL_MS = 8000;

const STATUS_LABELS: Record<ActiveJob["status"], string> = {
  waiting: "排隊中",
  running: "進行中",
  done: "已完成",
  failed: "失敗",
};

/** 全站生成進度鈴鐺（票 B4-warroom，模組邊界定案節「對外進入點」）：掛在全站殼層
 * Topbar，輪詢 `GET /api/jobs/active` 聚合端點——票 09 起七個 kind（建檔初掃／問答／
 * 貼回、人物誌生成、產品調研、智庫轉換、顧問分析報告）全部經 `app.background` 佇列讀
 * `llm_task`，沒有第二個機制，不含廣告分支（該節「不碰什麼」）。
 * 只讀不寫：沒有取消功能，點項目只是連去該筆工作所在的畫面。 */
export function ActiveJobsBell() {
  const [jobs, setJobs] = useState<ActiveJob[]>([]);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    function load() {
      fetchActiveJobs()
        .then((list) => !cancelled && setJobs(list))
        .catch(() => !cancelled && setJobs([]));
    }
    load();
    const timer = setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const activeCount = jobs.filter((j) => j.status === "waiting" || j.status === "running").length;

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label="生成進度"
        className="relative rounded-md p-2 text-muted-foreground hover:bg-muted hover:text-foreground"
      >
        <Bell className="h-5 w-5" aria-hidden="true" />
        {activeCount > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-medium text-primary-foreground">
            {activeCount}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 top-full z-50 mt-2 w-80 rounded-lg border border-border bg-card p-2 shadow-[var(--shadow-card)]">
          <p className="px-2 py-1 text-xs font-semibold text-muted-foreground">全站生成進度</p>
          {jobs.length === 0 ? (
            <p className="px-2 py-3 text-sm text-muted-foreground">目前沒有進行中的背景工作。</p>
          ) : (
            <ul className="flex flex-col gap-0.5">
              {jobs.map((job, i) => (
                <li key={i}>
                  {/* B0-16 同一種病：job.action_url 是後端算好、帶 `/app/` 前綴的完整路徑
                   * （app/brand_web／app/intake／app/ads 各自的 JobRegistry 呼叫端），設計上
                   * 給一般 <a href> 用——react-router 的 <Link to> 會再疊一次 `/app` basename，
                   * 變成 `/app/app/...`。改回一般 <a>。 */}
                  <a
                    href={job.action_url}
                    onClick={() => setOpen(false)}
                    className="flex flex-col gap-0.5 rounded-md px-2 py-1.5 text-sm hover:bg-muted"
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="font-medium text-foreground">{job.brand_name}</span>
                      <span
                        className={cn(
                          "shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-medium",
                          job.status === "failed" && "bg-danger/10 text-danger",
                          job.status === "done" && "bg-success/10 text-success",
                          (job.status === "running" || job.status === "waiting") && "bg-primary/10 text-primary",
                        )}
                      >
                        {STATUS_LABELS[job.status]}
                      </span>
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {ACTIVE_JOB_KIND_LABELS[job.kind]}・{job.stage}
                    </span>
                  </a>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
