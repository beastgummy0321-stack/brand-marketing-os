import { useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { confirmLaunchItemField, fetchLaunchView, readbackLaunch, type LaunchItem, type LaunchView } from "@/lib/adsLaunchApi";
import { confirmLaunchSetting, type SettingsReadbackKey } from "@/lib/adsLaunchSettingsApi";
import { ActionBar, Chip, DiffRow, ReadbackRow, ReadbackSummary, ResultHero, TodoRow, UnreadChip, type ChipTone } from "../patterns";
import { ItemTitle, PublishHead, campaignPath, fieldText, publishPath, timeText, type LaunchPlatform } from "./PublishFlow";

/** F30-I13 step 3 (prototype v10 `pubVerify()`, hash `pub/fall/verify`): one result hero over the items and the launch
 * settings (all the same／N differ／V of N checked, with the read time), each item's state with the approved value
 * beside the platform's for a mismatch, fields the read cannot see with 「我看過了，一樣」, the settings readback, and
 * 重新讀回. The next action depends on the case: 回活動總覽, 回平台改 or 繼續建剩下的. 「我看過了」 only records that
 * the user checked by eye; nothing is written to a platform. */

const errorText = (err: unknown, fallback: string) => (err instanceof Error && err.message ? err.message : fallback);

const CHIP: Record<LaunchItem["state"], [ChipTone, string]> = {
  verified: ["ok", "相符"], mismatch: ["warn", "不符"], built: ["neutral", "待讀回"], unknown: ["neutral", "待確認"],
  todo: ["neutral", "還沒建"], changed: ["warn", "有變更"],
};

export function PublishVerify({ brandId, campaignId, name, view, platform, onView }: {
  brandId: string;
  campaignId: string;
  name: string;
  view: LaunchView;
  platform: LaunchPlatform;
  onView: (view: LaunchView) => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

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
  const readAgain = () => run("readback", "讀回核對失敗，請稍後再試。", () => readbackLaunch(brandId, campaignId));

  const n = view.items.length;
  const ok = view.items.filter((i) => i.state === "verified").length;
  const dev = view.items.filter((i) => i.state === "mismatch").length;
  const todo = view.items.filter((i) => i.state === "todo" || i.state === "changed").length;
  const fields = view.settings_readback?.fields ?? [];
  const nDiff = fields.filter((f) => f.state === "differ").length;
  const nNa = fields.filter((f) => f.state === "unreadable").length;
  const nOk = fields.length - nDiff - nNa;
  const all = n > 0 && ok === n && nDiff === 0;
  const readAt = timeText(view.read_at);
  const at = readAt ? `讀回於 ${readAt}` : "還沒有讀回時間";

  const hero = all
    ? <ResultHero tone="ok" title={`${n} 項都和核准的一樣`} note={`${fields.length ? `投放設定 ${nOk} 項對上了${nNa ? `・${nNa} 項讀不到` : ""}・` : ""}${at}`} />
    : dev + nDiff > 0
      ? <ResultHero tone="warn" title={`${dev + nDiff} 項和核准的不一樣`} note={`其他 ${ok} 項已核對・${at}`} />
      : <ResultHero tone="neutral" mark={String(ok)} title={`${ok}／${n} 已核對`}
        note={[todo ? `還有 ${todo} 項沒建` : null, n - ok - todo ? `${n - ok - todo} 項待讀回或確認` : null, at].filter(Boolean).join("・")} />;

  return (
    <div className="flex flex-col gap-4">
      <PublishHead brandId={brandId} campaignId={campaignId} current={2} name={name} view={view} title="讀回核對" purpose="逐項比對平台上的設定" />
      {hero}
      <section aria-label="上架項目核對" className="surface px-[22px] py-5">
        {view.items.map((item, i) => {
          const [tone, label] = CHIP[item.state];
          const byKey = new Map(item.fields.map((f) => [f.key, f]));
          return (
            <TodoRow key={item.id} no={i + 1} state={item.state === "verified" ? "done" : item.state === "mismatch" ? "mismatch" : "open"}
              action={<Chip tone={tone}>{label}</Chip>}>
              <ItemTitle item={item} strong={false} />
              {item.mismatches.map((m) => (
                <DiffRow key={m.key} field={byKey.get(m.key)?.label ?? m.label} before={m.expected} after={m.observed}
                  beforeLabel="核准的" afterLabel={`${platform.label} 目前`} />
              ))}
              {item.unreadable.map((u) => (
                <div key={u.key} className="mt-2 flex flex-wrap items-center gap-2 text-xs">
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
              {item.reason && item.state !== "verified" && <p className="mt-1 text-xs text-warning">{item.reason}</p>}
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
      <ActionBar back={{ label: "到平台完成", to: publishPath(brandId, campaignId, "platform") }}>
        <Button variant="outline" disabled={busy !== null} onClick={() => void readAgain()}>{busy === "readback" ? "讀回中…" : "⟳ 重新讀回"}</Button>
        <Button asChild>
          {all ? <Link to={campaignPath(brandId, campaignId)}>回活動總覽 →</Link>
            : <Link to={publishPath(brandId, campaignId, "platform")}>{dev + nDiff > 0 ? "回平台改" : "繼續建剩下的"} →</Link>}
        </Button>
      </ActionBar>
    </div>
  );
}
