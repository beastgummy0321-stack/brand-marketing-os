import {useEffect, useState} from "react";
import {Link, useSearchParams} from "react-router-dom";
import {Button} from "@/components/layout/ui/button";
import {getNextPeriod, nextPeriodWizardHref, readContinuationQuery, withContinuationQuery,
  type NextPeriodPreparation} from "@/lib/adsWizardApi";
import {Disclosure, ReadFailed} from "../patterns";
import {FROM_META, isImported, rangeText} from "./settleCsv";

const REASONS: Record<string, string> = {
  above_target: "成本超過上限，不能當作成功沿用",
  current_target_not_met: "目前成本未達上限", mapping_required: "商品關聯尚未確認",
  objective_family_mismatch: "投放目標不同，僅保留歷史", material_unavailable: "原素材無法取得",
  coordinates_unknown: "受眾與訊息安排尚未核實", coverage_unknown: "來源資料尚未完整核實",
  target_unknown: "成本上限尚未核實", result_definition_unverified: "成果與歸因尚未核實",
  small_sample: "樣本少，僅供測試或對照",
};
type Read = {status: "loading"} | {status: "error"; message: string} |
  {status: "ready"; source: NextPeriodPreparation};

/** Opening this fold reads evidence only. Selection persists in the URL; creation belongs to the wizard. */
export function NextPeriodSources({brandId, month}: {brandId: string; month: string}) {
  const [params, setParams] = useSearchParams();
  const [read, setRead] = useState<Read>({status: "loading"});
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setRead({status: "loading"});
    getNextPeriod(brandId, month, controller.signal).then(source => {
      if (controller.signal.aborted) return;
      if (source.month !== month) throw new Error("來源月份不一致，請重新讀取。");
      setRead({status: "ready", source});
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setRead({status: "error", message: error instanceof Error ? error.message : "讀取失敗"});
    });
    return () => controller.abort();
  }, [brandId, month, tick]);
  if (read.status === "loading") return <p aria-busy="true" className="text-sm text-muted-foreground">正在核對完成期來源…</p>;
  if (read.status === "error") return <ReadFailed what={`下一期來源讀不到；尚未建立草稿（${read.message}）`} onRetry={() => setTick(t => t + 1)} />;
  const source = read.source;
  const query = readContinuationQuery(params);
  const selection = query.status === "ready" ? query.selection : null;
  const ids = selection?.campaign_ids ?? [];
  const valid = !!selection && selection.month === month && selection.revision === source.revision &&
    ids.every(id => source.source_campaigns.some(c => c.campaign_id === id));
  const update = (id: string, selected: boolean) => {
    const current = ids.filter(key => source.source_campaigns.some(c => c.campaign_id === key));
    const next = selected ? [...new Set([...current, id])] : current.filter(key => key !== id);
    setParams(withContinuationQuery(params, next.length ? {month, campaign_ids: next, revision: source.revision} : null), {replace: true});
  };
  const eligible = source.eligible_learning_refs.filter(ref => ids.includes(ref.campaign_id));
  return <div className="space-y-3 text-sm">
    <p className="text-muted-foreground">{month}・{rangeText(source.window.start, source.window.end)}。選來源後到下一期建檔；既有平台活動不會被關閉或改動。</p>
    {query.status !== "none" && !valid && <p role="alert" className="text-warning">來源選擇或版本已失效，請重新勾選；不會改成一般新建。</p>}
    {source.source_campaigns.length === 0 ? <p>這個完成期沒有可選的活動來源。</p> :
      <fieldset className="space-y-2"><legend className="mb-2 font-medium">下一期要參考哪些活動</legend>
        {source.source_campaigns.map(c => <label key={c.campaign_id} className="flex min-w-0 items-start gap-2 rounded-lg border border-border p-3">
          <input type="checkbox" className="mt-1 shrink-0" checked={ids.includes(c.campaign_id)} onChange={e => update(c.campaign_id, e.target.checked)} />
          <span className="min-w-0 [overflow-wrap:anywhere]"><span className="font-medium">{c.name}</span>
            <span className="mt-1 block text-xs text-muted-foreground">{isImported(c.origin) ? FROM_META : "本系統活動"}・成果 {c.result_kind ?? "未知"}・{c.currency ?? "幣別未知"}</span>
            {c.mapping_required && <span className="mt-1 block text-xs text-warning">商品關聯待確認；下一步需明確確認，不能推算商品成效。</span>}
          </span>
        </label>)}
      </fieldset>}
    <p className="text-xs text-muted-foreground">選定 {ids.length} 個來源・可沿用參考 {query.status === "none" ? "尚未選定" : valid ? `${eligible.length} 筆` : "尚未核實"}。來源被選中不代表每則素材都可沿用；對照用途也不等於市場已證實有效。沒有可沿用參考，仍可從這期歷史開始新測試。</p>
    <Disclosure label="查看來源資格與排除原因">
      <p className="text-xs [overflow-wrap:anywhere]">來源版本：{source.revision}</p>
      <ul className="mt-2 space-y-1 text-xs [overflow-wrap:anywhere]">
        {source.eligible_learning_refs.map(ref => <li key={`${ref.owner}:${ref.ref}`}>可沿用參考・{ref.owner} / {ref.ref}・來源活動 {ref.campaign_id}</li>)}
        {source.excluded.map((ref, i) => <li key={`${ref.owner}:${ref.ref}:${i}`}>未納入沿用・{ref.owner} / {ref.ref}：{REASONS[ref.reason_code] ?? `來源條件尚未符合（${ref.reason_code}）`}</li>)}
      </ul>
    </Disclosure>
    {valid && selection ? <Button variant="outline" asChild><Link to={nextPeriodWizardHref(brandId, selection)}>用選定來源規劃下一期 →</Link></Button> :
      <Button variant="outline" disabledReason="請先勾選並核實完成期來源">用選定來源規劃下一期 →</Button>}
  </div>;
}
