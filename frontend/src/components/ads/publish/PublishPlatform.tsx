import { useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { reportHandoff } from "@/lib/adsHandoffApi";
import { fetchLaunchView, readbackLaunch, unreportLaunchItem, type LaunchItem, type LaunchView } from "@/lib/adsLaunchApi";
import { ActionBar, Chip, CopyField, CopyFields, Disclosure, ResultHero, TodoRow } from "../patterns";
import { LaunchSettingsCopy } from "./LaunchSettingsCopy";
import { ItemTitle, LaunchProgress, PublishHead, awaitsReadback, campaignPath, fieldText, type LaunchPlatform } from "./PublishFlow";

/** F30-I13 step 2 (prototype v10 `pubPlatform()`, hash `pub/fall/platform`): open the platform's ads manager (an
 * external link only), the progress card, the approved launch settings to copy (F29 `LaunchSettingsCopy`), then one
 * row per item with its fields to copy and 我建好了／取消／我改好了. Verified items fold away. 讀回核對 reads back every
 * built item at once (Contract G) and is disabled until something is built. Only local records change here. */

const errorText = (err: unknown, fallback: string) => (err instanceof Error && err.message ? err.message : fallback);

export function PublishPlatform({ brandId, campaignId, name, view, platform, onView, onReadBack }: {
  brandId: string;
  campaignId: string;
  name: string;
  view: LaunchView;
  platform: LaunchPlatform;
  /** A refreshed launch view answered by the server. */
  onView: (view: LaunchView) => void;
  /** The batch readback answered: the page moves to 讀回核對. */
  onReadBack: (view: LaunchView) => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const pending = view.items.filter((i) => i.state !== "verified");
  const verified = view.items.filter((i) => i.state === "verified");
  const toRead = view.items.filter((i) => awaitsReadback(i.state)).length;
  const allVerified = view.items.length > 0 && pending.length === 0;

  async function run(key: string, fallback: string, action: () => Promise<LaunchView>, then: (v: LaunchView) => void = onView) {
    if (busy) return;
    setBusy(key); setError(null);
    try { then(await action()); }
    catch (err) { setError(errorText(err, fallback)); }
    finally { setBusy(null); }
  }
  const report = (item: LaunchItem) => run(item.id, "回報失敗，請稍後再試。", async () => {
    // 我改好了 on a mismatch: take the old report back, then report again — the item waits for the next readback.
    if (item.state === "mismatch") await unreportLaunchItem(brandId, campaignId, item.id);
    await reportHandoff(brandId, campaignId, item.id);
    return fetchLaunchView(brandId, campaignId);
  });
  const unreport = (item: LaunchItem) => run(item.id, "取消回報失敗，請稍後再試。", () => unreportLaunchItem(brandId, campaignId, item.id));
  const readBack = () => run("readback", "讀回核對失敗，請稍後再試。", () => readbackLaunch(brandId, campaignId), onReadBack);

  const row = (item: LaunchItem, index: number) => {
    const done = item.state === "verified";
    const byKey = new Map(item.fields.map((f) => [f.key, f]));
    const action = done ? <Chip tone="ok">已核對</Chip>
      : awaitsReadback(item.state) ? <Button size="sm" variant="ghost" disabled={busy !== null} onClick={() => void unreport(item)}>{busy === item.id ? "取消中…" : "取消"}</Button>
      : <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => void report(item)}>
        {busy === item.id ? "回報中…" : item.state === "mismatch" ? "我改好了" : "我建好了"}
      </Button>;
    return (
      <TodoRow key={item.id} no={index + 1} state={done ? "done" : item.state === "mismatch" ? "mismatch" : "open"} action={action}>
        <ItemTitle item={item}>
          {item.state === "mismatch" && item.mismatches.map((m) => (
            <Chip key={m.key} tone="warn">不符：{(byKey.get(m.key)?.label ?? m.label)}平台是 {m.observed === null ? "讀不到" : fieldText(m.observed)}</Chip>
          ))}
        </ItemTitle>
        {item.reason && !done && <p className="mt-1 text-xs text-warning">{item.reason}</p>}
        {!done && (
          <CopyFields>
            {item.fields.map((f) => <CopyField key={f.key} label={f.label} value={fieldText(f.value)} />)}
          </CopyFields>
        )}
      </TodoRow>
    );
  };
  const indexOf = (item: LaunchItem) => view.items.indexOf(item);

  return (
    <div className="flex flex-col gap-4">
      <PublishHead brandId={brandId} campaignId={campaignId} current={1} name={name} view={view} title="到平台完成" purpose="照清單在平台建，建好勾起來"
        aside={platform.href ? (
          <Button variant="outline" asChild>
            <a href={platform.href} target="_blank" rel="noreferrer">↗ 打開 {platform.label} 廣告管理員</a>
          </Button>
        ) : undefined} />
      <LaunchProgress view={view} />
      <LaunchSettingsCopy brandId={brandId} campaignId={campaignId} />
      <section aria-label="上架項目" className="surface px-[22px] py-5">
        {pending.length > 0 ? pending.map((item) => row(item, indexOf(item))) : <ResultHero tone="ok" title="全部核對完成" />}
        {verified.length > 0 && (
          <div className="mt-3">
            <Disclosure label={`已核對的 ${verified.length} 項`}>{verified.map((item) => row(item, indexOf(item)))}</Disclosure>
          </div>
        )}
      </section>
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      <ActionBar back={{ label: "還沒做完，先離開", to: `${campaignPath(brandId, campaignId)}?tab=changes` }}
        hint={allVerified || toRead ? undefined : "先勾起已建好的項目"}>
        {allVerified ? (
          <Button asChild><Link to={campaignPath(brandId, campaignId)}>回活動總覽 →</Link></Button>
        ) : (
          <Button disabled={busy !== null || toRead === 0} onClick={() => void readBack()}>
            {busy === "readback" ? "讀回中…" : `我在 ${platform.label} 做完了，讀回核對${toRead ? `（${toRead} 項）` : ""} →`}
          </Button>
        )}
      </ActionBar>
    </div>
  );
}
