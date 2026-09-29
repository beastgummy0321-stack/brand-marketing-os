import { useState } from "react";
import { Button } from "@/components/layout/ui/button";
import { formatSyncTime } from "@/lib/format";
import type { HandoffWorkspace } from "@/lib/adsHandoffApi";
import { confirmLaunchSetting, type SettingsReadback as Readback, type SettingsReadbackKey } from "@/lib/adsLaunchSettingsApi";
import { ReadbackRow, ReadbackSummary, ResultHero } from "../patterns";

/** Drill-7 #18, prototype `.rbbar` of `#/readback`: the yellow bar over the list — 「N 項讀不到」 with the reason the
 * payload gives for those fields in brackets (every distinct `reason` the readback returned; nothing invented when
 * it gives none), the primary 「我在 <platform> 都看過了，全部標記」 and 「逐項標記」. The host wires the two actions;
 * `busy` disables both while any action runs, `running` labels the primary while its own request is out. */
export function UnreadAllBar({ count, reasons, platform, busy = false, running = false, onAll, onEach }: {
  count: number; reasons: (string | null | undefined)[]; platform: string; busy?: boolean; running?: boolean;
  onAll: () => void; onEach: () => void;
}) {
  const reason = [...new Set(reasons.filter((r): r is string => typeof r === "string" && r.trim() !== ""))].join("；");
  return (
    <div data-slot="unread-all-bar" role="group" aria-label="全部標記" className="flex flex-wrap items-center gap-3 rounded-[10px] bg-zone-watch px-4 py-3">
      <span className="min-w-[220px] flex-1 text-sm">
        <b>{count} 項讀不到</b>
        {reason && <span className="ml-1 text-xs text-muted-foreground">（{reason}）</span>}
      </span>
      <Button disabled={busy} onClick={onAll}>{running ? "記錄中…" : `我在 ${platform} 都看過了，全部標記`}</Button>
      <Button variant="outline" disabled={busy} onClick={onEach}>逐項標記</Button>
    </div>
  );
}

/** F29-I16 verify stage (prototype v10 `pubVerify()` hero + 投放設定讀回 card, hash `pub/fall/verify`): every approved
 * launch setting against the platform read — 對上了, 不一樣 (the platform's value beside ours) or 讀不到 with its
 * reason and 「我看過了，一樣」. The hero counts the setting differences; 回平台改 when any differ. Nothing here
 * writes to a platform: 「我看過了」 only records that the user checked an unreadable field by eye. */
export function SettingsReadback({ brandId, campaignId, readback, platform = "平台", onConfirmed, onBackToPlatform }: {
  brandId: string; campaignId: string; readback: Readback;
  /** Where the values were read (the readback row's 「<platform> 上是 X」). */
  platform?: string;
  onConfirmed: (workspace: HandoffWorkspace) => void;
  /** The platform stage of the host page; without it there is no 回平台改. */
  onBackToPlatform?: () => void;
}) {
  const [busy, setBusy] = useState<SettingsReadbackKey | null>(null);
  const [error, setError] = useState("");
  const { fields } = readback;
  const differ = fields.filter((f) => f.state === "differ").length;
  const unread = fields.filter((f) => f.state === "unreadable").length;
  const matched = fields.length - differ - unread;
  const readAt = readback.read_at ? `讀回於 ${formatSyncTime(readback.read_at)}` : "還沒讀回時間";

  async function confirm(key: SettingsReadbackKey) {
    if (busy) return;
    setBusy(key); setError("");
    try { onConfirmed(await confirmLaunchSetting(brandId, campaignId, key)); }
    catch (err) { setError(err instanceof Error ? err.message : "確認失敗，請再按一次。"); }
    finally { setBusy(null); }
  }

  return (
    <div className="flex flex-col gap-4">
      {differ > 0 ? (
        <ResultHero tone="warn" title={`${differ} 項投放設定和核准的不一樣`} note={`其他 ${matched} 項對上了${unread ? `・${unread} 項讀不到` : ""}・${readAt}`} />
      ) : (
        <ResultHero tone="ok" title="投放設定都和核准的一樣" note={`${matched} 項對上了${unread ? `・${unread} 項讀不到，請到 ${platform} 看一眼` : ""}・${readAt}`} />
      )}
      <section aria-label="投放設定讀回" className="surface px-[22px] py-5">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-base font-semibold">投放設定讀回</h2>
          <ReadbackSummary fields={fields} />
        </div>
        <div>
          {fields.map((field) => (
            <ReadbackRow key={field.key} field={field} platform={platform} action={field.state === "unreadable" ? (
              <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => void confirm(field.key)}>
                {busy === field.key ? "記錄中…" : "我看過了，一樣"}
              </Button>
            ) : undefined} />
          ))}
        </div>
        {error && <p role="alert" className="mt-2 text-sm text-danger">{error}</p>}
        {differ > 0 && onBackToPlatform && (
          <div className="mt-3 flex flex-wrap items-center justify-end gap-2 border-t border-border pt-3">
            <small className="text-xs text-muted-foreground">到 {platform} 改成核准的值，再讀回一次</small>
            <Button onClick={onBackToPlatform}>回平台改 →</Button>
          </div>
        )}
      </section>
    </div>
  );
}
