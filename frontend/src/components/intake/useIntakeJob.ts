import { useEffect, useRef, useState } from "react";
import type { IntakeJobKind, IntakeJobState, LimitBlock } from "@/lib/intakeApi";
import { raiseBudgetAndRetry } from "@/lib/intakeApi";

/** 三種背景工作（初掃／出下一題／貼回修格式）共用的輪詢＋超限攔截邏輯（契約「背景工作
 * 機制」節）：進入這一步就自動呼叫一次 `start`；沒被超限攔下就每秒 `fetchStatus` 一次直到
 * done／failed；完成時呼叫 `onDone` 讓呼叫端重新整理草稿；被攔下時 `raise()` 一次做完
 * 「抬高上限＋重新啟動」（契約 S4.73）。三個真呼叫端（ScanStep／QuestionStep／PasteStep）
 * 共用同一份，不是預先設計的抽象。 */
export function useIntakeJob(
  brandId: string,
  kind: IntakeJobKind,
  active: boolean,
  start: () => Promise<{ limit_block: LimitBlock | null }>,
  fetchStatus: () => Promise<IntakeJobState>,
  onDone: () => void,
) {
  const [job, setJob] = useState<IntakeJobState | null>(null);
  const [limitBlock, setLimitBlock] = useState<LimitBlock | null>(null);
  const [raising, setRaising] = useState(false);
  const startedRef = useRef(false);

  async function kick() {
    setLimitBlock(null);
    setJob(null);
    const res = await start();
    if (res.limit_block) {
      setLimitBlock(res.limit_block);
      return;
    }
    setJob(await fetchStatus());
  }

  useEffect(() => {
    if (!active || startedRef.current) return;
    startedRef.current = true;
    void kick();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  useEffect(() => {
    if (!job || (job.status !== "running" && job.status !== "waiting")) return;
    const timer = setInterval(() => {
      void fetchStatus().then((s) => {
        setJob(s);
        if (s.status === "done") onDone();
      });
    }, 1000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.status]);

  async function raise() {
    setRaising(true);
    try {
      const res = await raiseBudgetAndRetry(brandId, kind);
      setLimitBlock(null);
      setJob(res.job);
      onDone(); // 上限剛被抬高，父層要重新整理草稿（花費儀表的上限要跟著變）
    } finally {
      setRaising(false);
    }
  }

  return { job, limitBlock, raising, retry: kick, raise };
}
