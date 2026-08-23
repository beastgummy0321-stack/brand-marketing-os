import { useEffect, useState } from "react";
import { SidePanel } from "@/components/layout/SidePanel";
import { fetchAutoChecks, fetchChecklist, toggleChecklistItem, toggleQaLaunchItem, type AutoCheckResult, type ChecklistItem } from "@/lib/warroomApi";
import { Badge } from "../../shared/Badge";

type ChecklistData = { items: ChecklistItem[]; qaChecks: AutoCheckResult[] };

// 決策 1（票 Q1-01）：系統驗過（available && passed）跟人工勾選一樣算「完成」，
// 跟 routes 層 readiness() 合併 qa_launch passed 用的判定同一套（`checked or (available and
// passed)`）——完成度數字不能只認 checked，不然畫面上明明五項全綠勾，數字卻卡住不動。
function qaDone(check: AutoCheckResult): boolean {
  return check.checked || (check.available && check.passed === true);
}

/** R5-4：交接區只露一行完成度；9 項原內容收在側板，異常訊號才留在主畫面。 */
export function ChecklistSection({ brandId, cycleId }: { brandId: string; cycleId: string }) {
  const [data, setData] = useState<ChecklistData | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);

  async function load() {
    const [items, qaChecks] = await Promise.all([fetchChecklist(brandId, cycleId), fetchAutoChecks(brandId, cycleId)]);
    setData({ items, qaChecks });
  }

  useEffect(() => {
    void load();
    // 這個效果只依品牌／檔期重抓一次，按勾選後由事件處理器主動重抓。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brandId, cycleId]);

  async function toggleChecklist(scope: "one-time" | "cycle", itemKey: string) {
    await toggleChecklistItem(brandId, cycleId, scope, itemKey);
    await load();
  }

  async function toggleQa(key: string) {
    await toggleQaLaunchItem(brandId, cycleId, key);
    await load();
  }

  if (!data) return <div className="rounded-lg border border-border bg-card px-4 py-3 text-sm text-muted-foreground">投放前檢查讀取中…</div>;

  const checklistDone = data.items.filter((item) => item.checked).length;
  const qaDoneCount = data.qaChecks.filter(qaDone).length;
  const doneCount = checklistDone + qaDoneCount;
  const total = data.items.length + data.qaChecks.length;
  const anomalyCount = data.items.filter((item) => item.flagged).length + data.qaChecks.filter((item) => item.available && item.passed === false).length;
  const oneTime = data.items.slice(0, 1);
  const cycleItems = data.items.slice(1);

  return (
    <>
      <div id="checklist-block" className="flex items-center justify-between gap-3 rounded-xl border border-border bg-card px-4 py-3 shadow-[var(--shadow-card)]">
        <div className="flex min-w-0 items-center gap-2">
          <p className="truncate text-sm font-medium text-foreground">投放前檢查 {doneCount}/{total}</p>
          {anomalyCount > 0 && <Badge tone="warning">異常訊號 {anomalyCount}</Badge>}
        </div>
        <button type="button" onClick={() => setPanelOpen(true)} className="shrink-0 rounded-md border border-primary px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/10">
          展開檢查
        </button>
      </div>

      {panelOpen && (
        <SidePanel ariaLabel="投放前檢查清單" onClose={() => setPanelOpen(false)}>
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="font-display text-xl text-foreground">投放前檢查</h2>
              <p className="mt-1 text-sm text-muted-foreground">{doneCount}/{total} 已確認；異常訊號不會擋住流程。</p>
            </div>
            <button type="button" onClick={() => setPanelOpen(false)} className="text-sm font-medium text-primary hover:underline">關閉</button>
          </div>

          <div className="flex flex-col gap-5">
            <section>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">檢查清單</p>
              <ul className="mt-2 flex flex-col gap-3 text-sm">
                {oneTime.map((item) => <ChecklistRow key={item.key} item={item} scope="one-time" onToggle={toggleChecklist} suffix="（品牌層，跨檔期共用）" />)}
                {cycleItems.map((item) => <ChecklistRow key={item.key} item={item} scope="cycle" onToggle={toggleChecklist} />)}
              </ul>
            </section>

            <section id="qa-launch-block">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">上線前提醒</p>
              <ul className="mt-2 flex flex-col gap-3 text-sm">
                {data.qaChecks.map((check) => {
                  // 決策 1（票 Q1-01）：系統驗過就不畫勾選框，只有「驗不了」或「驗了沒過」才需要人來勾——
                  // 跟 qaDone() 是兩個不同的判定：這裡不看 checked（勾選框本身不能靠自己隱藏自己）。
                  const verified = check.available && check.passed === true;
                  return (
                    <li key={check.key} className="rounded-md border border-border p-3">
                      <div className="flex items-start justify-between gap-3">
                        {verified ? (
                          <span className="text-foreground">{check.label}</span>
                        ) : (
                          <label className="flex items-start gap-2 text-foreground">
                            <input type="checkbox" checked={check.checked} onChange={() => void toggleQa(check.key)} className="mt-0.5" />
                            <span>{check.label}</span>
                          </label>
                        )}
                        {verified ? (
                          <Badge tone="success">系統已驗過</Badge>
                        ) : check.available ? (
                          <Badge tone="danger">系統覆核：未過</Badge>
                        ) : (
                          <Badge>系統無法覆核</Badge>
                        )}
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">{check.note}</p>
                    </li>
                  );
                })}
              </ul>
            </section>
          </div>
          <p className="text-xs text-muted-foreground">不擋流程：覆核不通過或還沒自行確認，照樣可以往下一步。</p>
        </SidePanel>
      )}
    </>
  );
}

function ChecklistRow({
  item,
  scope,
  onToggle,
  suffix = "",
}: {
  item: ChecklistItem;
  scope: "one-time" | "cycle";
  onToggle: (scope: "one-time" | "cycle", itemKey: string) => void;
  suffix?: string;
}) {
  return (
    <li className="flex items-start gap-2 rounded-md border border-border p-3">
      <input type="checkbox" checked={item.checked} onChange={() => void onToggle(scope, item.key)} className="mt-0.5" />
      <span className="min-w-0 text-foreground">
        {item.label}{suffix}
        {item.flagged && <span className="ml-1"><Badge tone="warning">{item.flagged_reason ?? "異常訊號"}</Badge></span>}
        {item.hint && <span className="ml-1"><Badge tone="warning">{item.hint}</Badge></span>}
        <span className="block text-xs text-muted-foreground">{item.help}</span>
      </span>
    </li>
  );
}
