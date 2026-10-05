import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { confirmAllLaunchFields, confirmLaunchItemField, fetchLaunchView, readbackLaunch, type LaunchItem, type LaunchView } from "@/lib/adsLaunchApi";
import { confirmLaunchSetting, type SettingsReadbackKey } from "@/lib/adsLaunchSettingsApi";
import { ActionBar, Chip, DiffRow, ReadbackRow, ReadbackSummary, ResultHero, TodoRow, UnreadChip, type ChipTone } from "../patterns";
import { ItemTitle, PublishHead, campaignPath, fieldText, publishPath, readFailedText, readbackReason, timeText, type LaunchPlatform } from "./PublishFlow";
import { UnreadAllBar } from "./SettingsReadback";
import { useOrgClock } from "@/lib/orgClock";

/** F30-I13 step 3 (prototype v10 `pubVerify()`, hash `pub/fall/verify`): one result hero over the items and the launch
 * settings (all the same／N differ／V of N checked, with the read time), each item's state with the approved value
 * beside the platform's for a mismatch, fields the read cannot see with 「我看過了，一樣」, the settings readback, and
 * 重新讀回. The next action depends on the case: 回活動總覽, 回平台改 or 繼續建剩下的. 「我看過了」 only records that
 * the user checked by eye; nothing is written to a platform.
 * Drill-7 #18 (F40 prototype `#/readback`): while any field is still unreadable, one bar over the list marks them all
 * in one request; 回活動總覽 waits until the view reports nothing unreadable.
 * F49 Contract B (decision 5): each item's word is the served `state_label`; the fields no platform read can see were
 * confirmed once, at approval, and show under 「核准時已確認」 without a button — only a read gap the platform could
 * have answered (`unreadable`) still asks for the eye, and only those are counted as 讀不到. An `unknown` item prints
 * its coded reason (`readbackReason`). */

const errorText = (err: unknown, fallback: string) => (err instanceof Error && err.message ? err.message : fallback);

/** The chip's colour follows the state; its word is served. */
const tone = (state: LaunchItem["state"]): ChipTone =>
  state === "verified" ? "ok" : state === "mismatch" || state === "changed" ? "warn" : "neutral";

const UNREAD_SELECTOR = "[data-slot=item-unread][data-variant=unreadable] button, [data-slot=readback-row][data-variant=unreadable] button";

export function PublishVerify({ brandId, campaignId, name, view, platform, onView }: {
  brandId: string;
  campaignId: string;
  name: string;
  view: LaunchView;
  platform: LaunchPlatform;
  onView: (view: LaunchView) => void;
}) {
  const { timezone } = useOrgClock();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  async function run(key: string, fallback: string, action: () => Promise<LaunchView>) {
    if (busy) return;
    setBusy(key); setError(null);
    try { onView(await action()); }
    catch (err) { setError(errorText(err, fallback)); }
    finally { setBusy(null); }
  }
  const confirmField = (item: LaunchItem, key: string) =>
    run(`${item.id}:${key}`, "確認失敗，請再按一次。", () => confirmLaunchItemField(brandId, campaignId, item.id, key));
  // The settings confirm answers with the handoff workspace; the launch view is read again for the page.
  const confirmSetting = (key: SettingsReadbackKey) => run(`setting:${key}`, "確認失敗，請再按一次。", async () => {
    await confirmLaunchSetting(brandId, campaignId, key);
    return fetchLaunchView(brandId, campaignId);
  });
  const confirmAll = () => run("all", "全部標記失敗，請再按一次。", () => confirmAllLaunchFields(brandId, campaignId));
  const readAgain = () => run("readback", "讀回核對失敗，請稍後再試。", () => readbackLaunch(brandId, campaignId));
  // 「逐項標記」 only moves the user to the first field still waiting for their eye.
  const goToFirstUnread = () => {
    const first = listRef.current?.querySelector<HTMLElement>(UNREAD_SELECTOR);
    first?.scrollIntoView?.({ block: "center", behavior: "smooth" });
    first?.focus();
  };

  const n = view.items.length;
  const ok = view.items.filter((i) => i.state === "verified").length;
  const dev = view.items.filter((i) => i.state === "mismatch").length;
  const todo = view.items.filter((i) => i.state === "todo" || i.state === "changed").length;
  const fields = view.settings_readback?.fields ?? [];
  const nDiff = fields.filter((f) => f.state === "differ").length;
  const nNa = fields.filter((f) => f.state === "unreadable").length;
  const nMatch = fields.filter((f) => f.state === "match").length;
  const nSeenSettings = fields.filter((f) => f.state === "self_confirmed").length;
  // Fields the read could not see: still waiting for the user's eye (unread) or already confirmed by it (seen).
  const unreadItemFields = view.items.flatMap((i) => i.unreadable.filter((u) => !u.confirmed));
  const seen = nSeenSettings + view.items.reduce((s, i) => s + i.unreadable.filter((u) => u.confirmed).length, 0);
  const unread = nNa + unreadItemFields.length;
  const blockedItems = view.items.filter((i) => i.state !== "verified" && i.unreadable.some((u) => !u.confirmed)).length;
  // Items the platform still has to answer for: built or read without an answer, beyond those only waiting on an eye.
  const awaiting = n - ok - dev - todo - blockedItems;
  const all = n > 0 && ok === n && nDiff === 0 && nNa === 0;
  const readAt = timeText(view.read_at, timezone);
  const at = readAt ? `讀回於 ${readAt}` : "還沒有讀回時間";
  const reasons = [
    ...fields.filter((f) => f.state === "unreadable").map((f) => f.reason),
    ...view.items.filter((i) => i.unreadable.some((u) => !u.confirmed)).map(readbackReason),
  ];
  const settingsNote = fields.length ? `・投放設定 ${nMatch} 項對上了` : "";
  // Declared fields: confirmed by the approval, named in the note, never counted as 讀不到.
  const atApproval = view.items.reduce((s, i) => s + (i.confirmed_at_approval?.length ?? 0), 0);
  const approvalNote = atApproval ? `・${atApproval} 項核准時已確認` : "";

  const hero = all
    ? seen > 0
      ? <ResultHero tone="ok" title="投放設定都核對過了" note={`${n} 項都和核准的一樣${settingsNote}・${seen} 項你在 ${platform.label} 看過${approvalNote}・${at}`} />
      : <ResultHero tone="ok" title={`${n} 項都和核准的一樣`} note={[
        fields.length ? `投放設定 ${nMatch} 項對上了` : null, atApproval ? `${atApproval} 項核准時已確認` : null, at,
      ].filter(Boolean).join("・")} />
    : dev + nDiff > 0
      ? <ResultHero tone="warn" title={`${dev + nDiff} 項和核准的不一樣`} note={`其他 ${ok} 項已核對・${at}`} />
      : unread > 0 && todo === 0 && awaiting === 0
        ? <ResultHero tone="warn" mark="!" title={`${unread} 項還沒核對`}
          note={`${ok} 項已核對${settingsNote}${seen ? `・${seen} 項你看過` : ""}・${unread} 項讀不到，請到 ${platform.label} 看一眼・${at}`} />
        : <ResultHero tone="neutral" mark={String(ok)} title={`${ok}／${n} 已核對`}
          note={[todo ? `還有 ${todo} 項沒建` : null, n - ok - todo ? `${n - ok - todo} 項待讀回或確認` : null, at].filter(Boolean).join("・")} />;

  // Nothing left to build or fix and every item still open was read without an answer for a coded reason (a read gap,
  // never a build step): the way forward is reading again, not 繼續建剩下的 (drill 11, B/p1-ad-error3-pending2).
  const open = view.items.filter((i) => i.state !== "verified");
  const readAgainOnly = !all && dev + nDiff === 0 && todo === 0 && open.length > 0
    && open.every((i) => i.state === "unknown" && Boolean(i.reason_code));
  const readAgainLabel = busy === "readback" ? "讀回中…" : "⟳ 重新讀回";

  const primary = all
    ? <Button asChild><Link to={campaignPath(brandId, campaignId)}>回活動總覽 →</Link></Button>
    : dev + nDiff > 0
      ? <Button asChild><Link to={publishPath(brandId, campaignId, "platform")}>回平台改 →</Link></Button>
      : readAgainOnly
        ? <Button disabled={busy !== null} onClick={() => void readAgain()}>{readAgainLabel}</Button>
      : todo + awaiting > 0 || unread === 0
        ? <Button asChild><Link to={publishPath(brandId, campaignId, "platform")}>繼續建剩下的 →</Link></Button>
        : <Button disabled>回活動總覽 →</Button>;
  const waitingOnEye = !all && dev + nDiff === 0 && todo + awaiting === 0 && unread > 0;

  return (
    <div className="flex flex-col gap-4" ref={listRef}>
      <PublishHead brandId={brandId} campaignId={campaignId} current={2} name={name} view={view} title="讀回核對" purpose="逐項比對平台上的設定" />
      {hero}
      {unread > 0 && (
        <UnreadAllBar count={unread} reasons={reasons} platform={platform.label} busy={busy !== null} running={busy === "all"}
          onAll={() => void confirmAll()} onEach={goToFirstUnread} />
      )}
      <section aria-label="上架項目核對" className="surface px-[22px] py-5">
        {view.items.map((item, i) => {
          const byKey = new Map(item.fields.map((f) => [f.key, f]));
          const reason = readbackReason(item);
          return (
            <TodoRow key={item.id} no={i + 1} state={item.state === "verified" ? "done" : item.state === "mismatch" ? "mismatch" : "open"}
              action={item.state_label ? <Chip tone={tone(item.state)} data-state={item.state}>{item.state_label}</Chip> : undefined}>
              <ItemTitle item={item} strong={false} />
              {item.mismatches.map((m) => (
                <DiffRow key={m.key} field={byKey.get(m.key)?.label ?? m.label} before={m.expected} after={m.observed}
                  beforeLabel="核准的" afterLabel={`${platform.label} 目前`} />
              ))}
              {item.unreadable.map((u) => (
                <div key={u.key} data-slot="item-unread" data-variant={u.confirmed ? "confirmed" : "unreadable"} className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                  <span className="text-muted-foreground">{byKey.get(u.key)?.label ?? u.label}</span>
                  <b className="min-w-0 font-semibold [overflow-wrap:anywhere]">{fieldText(byKey.get(u.key)?.value ?? null)}</b>
                  {u.confirmed ? <Chip tone="ok">你確認一樣</Chip> : <>
                    <UnreadChip />
                    <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => void confirmField(item, u.key)}>
                      {busy === `${item.id}:${u.key}` ? "記錄中…" : "我看過了，一樣"}
                    </Button>
                  </>}
                </div>
              ))}
              {(item.confirmed_at_approval ?? []).map((c) => (
                <div key={c.key} data-slot="item-approved" className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                  <span className="text-muted-foreground">{byKey.get(c.key)?.label ?? c.label}</span>
                  {byKey.has(c.key) && <b className="min-w-0 font-semibold [overflow-wrap:anywhere]">{fieldText(byKey.get(c.key)?.value ?? null)}</b>}
                  <Chip>核准時已確認</Chip>
                </div>
              ))}
              {reason && (
                // F47-I06 (R5): a stored reason says when it was read; 重新讀回 below replaces it with the new read.
                <p data-slot="readback-error" className="mt-1 text-xs text-warning">{readFailedText(item.reason_at, reason, timezone)}</p>
              )}
            </TodoRow>
          );
        })}
      </section>

      {view.settings_readback && (
        <section aria-label="投放設定讀回" className="surface px-[22px] py-5">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-base font-semibold">投放設定讀回</h2>
            <ReadbackSummary fields={fields} />
          </div>
          {fields.map((field) => (
            <ReadbackRow key={field.key} field={field} platform={platform.label} action={field.state === "unreadable" ? (
              <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => void confirmSetting(field.key)}>
                {busy === `setting:${field.key}` ? "記錄中…" : "我看過了，一樣"}
              </Button>
            ) : undefined} />
          ))}
        </section>
      )}

      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      <ActionBar back={{ label: "到平台完成", to: publishPath(brandId, campaignId, "platform") }} hint={waitingOnEye ? "全部核對完才算上架完成" : undefined}>
        {/* When reading again is the primary action, it is the one button (no second outline twin). */}
        {!readAgainOnly && <Button variant="outline" disabled={busy !== null} onClick={() => void readAgain()}>{readAgainLabel}</Button>}
        {primary}
      </ActionBar>
    </div>
  );
}
