import { useEffect, useState } from "react";
import { fetchAutoChecks, toggleQaLaunchItem, type AutoCheckResult } from "@/lib/warroomApi";
import { Badge } from "../../shared/Badge";

/** 上線前 QA 五項提醒（S8.31-36）：既有「已確認／尚未確認」自行勾選＋本票新增「系統覆核」
 * 小標。②③兩項 `available=false`——目前技術上做不到系統覆核，維持純自行確認（契約
 * 「拿不準的點」第 1 點，不是本票自己判斷）。 */
export function QaAutoCheckSection({ brandId, cycleId }: { brandId: string; cycleId: string }) {
  const [checks, setChecks] = useState<AutoCheckResult[] | null>(null);
  const [confirmed, setConfirmed] = useState<Set<string>>(new Set());

  useEffect(() => {
    fetchAutoChecks(brandId, cycleId).then((data) => {
      setChecks(data);
      setConfirmed(new Set(data.filter((c) => c.checked).map((c) => c.key)));
    });
  }, [brandId, cycleId]);

  async function toggleConfirm(key: string) {
    await toggleQaLaunchItem(brandId, cycleId, key);
    setConfirmed((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  if (!checks) return <div className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">讀取中…</div>;

  return (
    <div id="qa-launch-block" className="rounded-lg border border-border bg-card p-4 shadow-[var(--shadow-card)]">
      <p className="font-medium text-foreground">上線前提醒</p>
      <ul className="mt-2 flex flex-col gap-2 text-sm">
        {checks.map((c) => {
          // 決策 1（票 Q1-01）：系統驗過就不畫勾選框，只有「驗不了」或「驗了沒過」才需要人來勾。
          const verified = c.available && c.passed;
          return (
            <li key={c.key} className="flex flex-col gap-1 rounded-md border border-border p-2">
              <div className="flex items-center justify-between gap-2">
                {verified ? (
                  <span className="text-foreground">{c.label}</span>
                ) : (
                  <label className="flex items-center gap-2 text-foreground">
                    <input type="checkbox" checked={confirmed.has(c.key)} onChange={() => void toggleConfirm(c.key)} />
                    {c.label}
                  </label>
                )}
                {verified ? (
                  <Badge tone="success">系統已驗過</Badge>
                ) : c.available ? (
                  <Badge tone="danger">系統覆核：未過</Badge>
                ) : (
                  <Badge>系統無法覆核</Badge>
                )}
              </div>
              <p className="text-xs text-muted-foreground">{c.note}</p>
            </li>
          );
        })}
      </ul>
      <p className="mt-2 text-xs text-muted-foreground">不擋流程：覆核不通過或還沒自行確認，照樣可以往下一步。</p>
    </div>
  );
}
