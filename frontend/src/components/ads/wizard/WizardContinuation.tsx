import {useEffect, useState} from "react";
import {Link} from "react-router-dom";
import {getNextPeriod, withContinuationQuery, type ContinuationQuery, type NextPeriodPreparation} from "@/lib/adsWizardApi";
import {Disclosure, ReadFailed} from "../patterns";
import {qualificationReason} from "../strategy/StrategyQualification";

type Read = {status: "loading"} | {status: "error"; message: string} | {status: "ready"; data: NextPeriodPreparation};
export function useContinuation(brand: string, query: ContinuationQuery) {
  const selection = query.status === "ready" ? query.selection : null;
  const signature = selection ? JSON.stringify(selection) : query.status;
  const [read, setRead] = useState<Read>({status: "loading"});
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!selection) return;
    const controller = new AbortController();
    setRead({status: "loading"});
    getNextPeriod(brand, selection.month, controller.signal).then(data => {
      if (controller.signal.aborted) return;
      if (data.month !== selection.month || data.revision !== selection.revision ||
          selection.campaign_ids.some(id => !data.source_campaigns.some(c => c.campaign_id === id))) {
        throw new Error("來源月份、活動或版本已失效；請返回完成期重新選擇。");
      }
      setRead({status: "ready", data});
    }).catch(error => {
      if (!controller.signal.aborted) setRead({status: "error", message: error instanceof Error ? error.message : "來源讀取失敗"});
    });
    return () => controller.abort();
  // The serialized selection is the dependency; URLSearchParams creates new objects each render.
  }, [brand, signature, tick]); // eslint-disable-line react-hooks/exhaustive-deps
  return {query, read, retry: () => setTick(value => value + 1), selection,
    valid: query.status === "ready" && read.status === "ready" && read.data.month === selection?.month &&
      read.data.revision === selection.revision && selection.campaign_ids.every(id => read.data.source_campaigns.some(c => c.campaign_id === id))};
}

export function WizardContinuation({source, brand, productChosen, confirmed, onConfirm, locked}: {
  source: ReturnType<typeof useContinuation>; brand: string; productChosen: boolean;
  confirmed: boolean; onConfirm: (value: boolean) => void; locked: boolean;
}) {
  if (source.query.status === "none") return null;
  const selection = source.selection;
  return <section className="surface" aria-label="下一期來源">
    <div className="surface-header"><h2>接續完成期來源</h2>
      {selection && <Link className="text-sm text-primary" to={`/brands/${encodeURIComponent(brand)}/ads/settle/${selection.month}?${withContinuationQuery(new URLSearchParams({step:"result"}),selection)}`}>返回來源選擇 →</Link>}
    </div>
    <div className="surface-body space-y-3 text-sm">
      {source.query.status === "invalid" ? <p role="alert">來源連結不完整；不能改成一般新建，請返回完成期重新選擇。</p>
        : source.read.status === "loading" ? <p aria-busy="true">核對完成期來源中…</p>
        : source.read.status === "error" ? <ReadFailed what={source.read.message} onRetry={source.retry} /> : <>
          <p>{source.read.data.month}・{source.read.data.window.start}～{source.read.data.window.end}。既有平台活動保持原狀，確認後建立內部規劃草稿。</p>
          <ul className="space-y-1 [overflow-wrap:anywhere]">{source.read.data.source_campaigns.filter(c => selection?.campaign_ids.includes(c.campaign_id)).map(c =>
            <li key={c.campaign_id}>{c.name}・{c.origin === "internal" ? "本系統活動" : "既有平台活動"}・{c.currency ?? "幣別未知"}</li>)}</ul>
          {source.read.data.source_campaigns.some(c => selection?.campaign_ids.includes(c.campaign_id) && c.mapping_required) && <>
            <label className="flex items-start gap-2"><input type="checkbox" checked={confirmed} disabled={locked || !productChosen} onChange={e => onConfirm(e.target.checked)} />
              我確認選定歷史活動推的是目前選擇的商品</label>
            <p className="text-xs text-muted-foreground">{confirmed ? "已記錄你的關聯確認，素材資格仍待送出時由系統核實。" : "未確認關聯時仍可開始新測試，商品專屬成功素材不會自動沿用。"}這不是訂單歸因證明。</p>
          </>}
          <Disclosure label="查看來源資格與限制">
            <p className="text-xs [overflow-wrap:anywhere]">版本 {source.read.data.revision}</p>
            <ul className="mt-2 space-y-1 text-xs [overflow-wrap:anywhere]">
              {source.read.data.eligible_learning_refs.filter(ref => selection?.campaign_ids.includes(ref.campaign_id)).map(ref => <li key={`${ref.owner}:${ref.ref}`}>來源參考 {ref.owner} / {ref.ref}；對照用途不等於市場已證實有效。</li>)}
              {source.read.data.excluded.map((ref, i) => <li key={`${ref.owner}:${ref.ref}:${i}`}>未納入沿用 {ref.owner} / {ref.ref}：{qualificationReason(ref.reason_code)}</li>)}
            </ul>
          </Disclosure>
        </>}
    </div>
  </section>;
}
