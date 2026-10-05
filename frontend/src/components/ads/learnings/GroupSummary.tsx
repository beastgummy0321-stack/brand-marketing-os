import type { LearningGroup } from "@/lib/adsLearningsApi";
import { cn } from "@/lib/utils";
import { Chip } from "../patterns/Chip";
import { learnMoney } from "./LearningsTable";

/** 各顧客群 (prototype `groupSummary`): one bar per customer group, its cost per sale against its own cap (a vertical
 * line). Groups arrive sorted by cost per sale (沒賣出 last) and are printed in that order. A group with `cap: null`
 * draws no cap line and no 低於／高於上限 chip; `cost_per_sale: null` prints 沒賣出 with an empty bar.
 * The cap label is printed on the first bar and wherever the cap changes from the bar above. */
export function GroupSummary({ groups }: { groups: LearningGroup[] }) {
  const scale = Math.max(1, ...groups.flatMap((g) => [g.caps_differ ? null : g.cap, g.cost_per_sale].filter((v): v is number => v !== null))) * 1.12;
  return (
    <div role="list" aria-label="各顧客群每筆成本" className="flex flex-col gap-2.5 pt-3.5">
      {groups.map((g, i) => {
        const per = g.cost_per_sale;
        const cap = g.caps_differ ? null : g.cap;
        const judged = per !== null && cap !== null;
        const ok = judged && per <= (cap as number);
        const showCapLabel = cap !== null && (i === 0 || groups[i - 1].cap !== g.cap);
        return (
          <div
            key={g.customer_group_id}
            role="listitem"
            data-group={g.customer_group_id}
            className="grid grid-cols-[150px_minmax(0,1fr)_220px] items-center gap-3.5 max-[900px]:grid-cols-[minmax(0,1fr)_auto] max-[900px]:gap-x-2.5 max-[900px]:gap-y-1.5 max-[900px]:[grid-template-areas:'gn_gv'_'tr_tr']"
          >
            <div className="min-w-0 max-[900px]:[grid-area:gn]">
              <b className="block text-sm [overflow-wrap:anywhere]">{g.who}</b>
              <span className="text-xs text-muted-foreground">{g.ads} 則・花 {learnMoney(g.spend)}・成交 {g.sales ?? "不明"}</span>
            </div>
            <div aria-hidden="true" className="relative h-[22px] rounded-md bg-muted max-[900px]:mt-3.5 max-[900px]:[grid-area:tr]">
              {per !== null && (
                <div
                  className={cn("absolute inset-y-0 left-0 rounded-md", !judged ? "bg-grade-thin" : ok ? "bg-zone-ok" : "bg-zone-over")}
                  style={{ width: `${(per / scale) * 100}%` }}
                />
              )}
              {cap !== null && (
                <div className="absolute -top-1 -bottom-1 w-0.5 bg-foreground" style={{ left: `${(cap / scale) * 100}%` }}>
                  {showCapLabel && (
                    <em className="absolute -top-[18px] left-1/2 -translate-x-1/2 whitespace-nowrap text-[11px] not-italic text-foreground">
                      上限 {learnMoney(cap)}
                    </em>
                  )}
                </div>
              )}
            </div>
            <div className="flex items-center justify-end gap-2 text-[13px] max-[900px]:[grid-area:gv]">
              <span className="text-muted-foreground">每筆</span>
              <b className={cn("text-base tabular-nums", per === null && "text-sm font-medium text-muted-foreground")}>
                {per === null ? (g.sales === 0 ? "沒賣出" : "不明") : learnMoney(per)}
              </b>
              {g.caps_differ && <span className="text-xs text-muted-foreground">各活動上限或幣別不同</span>}
              {judged && <Chip tone={ok ? "ok" : "bad"}>{ok ? "低於上限" : "高於上限"}</Chip>}
            </div>
          </div>
        );
      })}
    </div>
  );
}
