import { campaignPath } from "@/lib/adsRoutes";
import { isRejected } from "@/lib/http";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { assignPlannedMaterial, getPlannedMaterials, reapproveLaunch, revertLaunch, type HandoffItem, type HandoffWorkspace, type LaunchDiffRow, type LaunchStale, type PlannedMaterialWorkspace } from "@/lib/adsHandoffApi";
import { formatInstant, useOrgClock } from "@/lib/orgClock";
import { ActionBar, CampaignChip, Chip, ConfirmSheet, DiffRow, FlowHeader, formatAmount, ProgressSegments, ResultHero, TodoRow, WarnButton, type SegmentState } from "./patterns";

/** Feature F28 "Stale launch" (prototype v9 `pubStale()` + `act.revertOpen`): the approved launch no longer
 * matches the plan. The user either re-approves the current plan or writes the approved values back; per-item
 * platform checks wait until one of the two is done. Rendered by `ManualHandoffPanel` whenever `launch_stale`
 * is present. */

export type LaunchOutcome = { tone: "ok" | "error"; text: string };
type Props = {
  brandId: string; campaignId: string; stale: LaunchStale; items: HandoffItem[];
  /** The server confirmed the decision and answered with the refreshed handoff. */
  onDecided: (workspace: HandoffWorkspace, outcome: LaunchOutcome) => void;
  /** Read the handoff again (after a refusal, an unknown outcome or a material re-assignment). */
  onReload: (outcome?: LaunchOutcome) => void;
};

const KIND: Record<string, string> = { campaign: "活動", group: "投放組", adset: "投放組", ad: "廣告" };
const STEPS = [{ label: "確認上架清單" }, { label: "到平台完成" }, { label: "讀回核對" }];

/** An instant as 「MM/DD HH:MM」 on the org clock; missing or unreadable → null. */
const when = (iso: string | null, timezone: string) => formatInstant(iso, timezone, "md_hm") || null;
/** A diffed value as the DiffRow prints it: null/empty stays unknown (未設定), never 0 or an empty box. */
function valueOf(value: unknown): string | number | null {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "boolean") return value ? "是" : "否";
  if (Array.isArray(value)) return value.length ? value.map(v => valueOf(v) ?? "未設定").join("、") : null;
  if (typeof value === "object") return Object.values(value).map(v => valueOf(v)).filter(v => v !== null).join("、") || null;
  return String(value);
}
const printed = (value: unknown) => { const v = valueOf(value); return v === null ? "未設定" : typeof v === "number" ? formatAmount(v) ?? "未設定" : v; };
const reason = (error: unknown) => (error instanceof Error ? error.message : "結果尚未確認。").replace(/[。.]?$/, "。");

export function LaunchStalePanel({ brandId, campaignId, stale, items, onDecided, onReload }: Props) {
  const { timezone } = useOrgClock();
  const [busy, setBusy] = useState<"" | "reapprove" | "revert" | "assign">("");
  const [sheet, setSheet] = useState(false);
  const [materials, setMaterials] = useState<PlannedMaterialWorkspace | null>(null);
  const [materialError, setMaterialError] = useState("");
  const [materialLoad, setMaterialLoad] = useState(0);
  const lifetime = useRef(new AbortController());
  const sheetRef = useRef<HTMLDivElement>(null);
  useEffect(() => { lifetime.current = new AbortController(); return () => lifetime.current.abort(); }, []);

  const launchItems = items.filter(item => item.change_set_id === stale.change_set_id);
  const changed = new Set(stale.diff.map(row => row.item_id).filter(Boolean));
  const hasMaterialRow = stale.diff.some(row => row.field === "material");
  // Only a material difference needs the planned-ad assignments (a revised version must be re-pointed first).
  useEffect(() => {
    if (!hasMaterialRow) return;
    const controller = new AbortController();
    getPlannedMaterials(brandId, campaignId, controller.signal)
      .then(value => { if (!controller.signal.aborted) { setMaterials(value); setMaterialError(""); } })
      .catch(err => { if (!controller.signal.aborted) setMaterialError(reason(err)); });
    return () => controller.abort();
  }, [brandId, campaignId, hasMaterialRow, materialLoad, stale.content_hash]);
  useEffect(() => {
    if (!sheet) return;
    sheetRef.current?.scrollIntoView?.({ block: "center" });
    sheetRef.current?.querySelector<HTMLButtonElement>("[data-variant=warn]")?.focus();
  }, [sheet]);

  const plannedAd = (row: LaunchDiffRow) => {
    const item = launchItems.find(entry => entry.id === row.item_id);
    return item ? materials?.planned_ads.find(ad => ad.id === item.planned_id) : undefined;
  };
  const needsMaterial = materials?.planned_ads.filter(ad => ad.assignment_status === "stale") ?? [];

  async function decide(kind: "reapprove" | "revert") {
    if (busy) return;
    const signal = lifetime.current.signal;
    setBusy(kind);
    try {
      const body = { change_set_id: stale.change_set_id, content_hash: stale.content_hash };
      const workspace = kind === "reapprove" ? await reapproveLaunch(brandId, campaignId, body, signal) : await revertLaunch(brandId, campaignId, body, signal);
      if (signal.aborted) return;
      setSheet(false);
      onDecided(workspace, { tone: "ok", text: kind === "reapprove" ? "已用現在的方案重新核准；沒有變的已核對項目保留結果。" : "已改回核准時的設定；原本的核准繼續有效。" });
    } catch (err) {
      if (signal.aborted) return;
      setSheet(false);
      // 409: the plan moved again (or the decision no longer applies) — show the newest difference, never a success.
      onReload({ tone: "error", text: isRejected(err) ? `沒有完成：${reason(err)}已重新載入最新的差異，請再看一次。` : `${reason(err)}已重新載入，請確認目前狀態後再決定。` });
    } finally { if (!signal.aborted) setBusy(""); }
  }
  async function reassign(adId: string, placementId: string, revision: number) {
    if (busy) return;
    const signal = lifetime.current.signal;
    setBusy("assign"); setMaterialError("");
    try {
      await assignPlannedMaterial(brandId, campaignId, adId, { placement_id: placementId, revision }, signal);
      if (signal.aborted) return;
      setMaterialLoad(n => n + 1);
      onReload();
    } catch (err) { if (!signal.aborted) setMaterialError(reason(err)); }
    finally { if (!signal.aborted) setBusy(""); }
  }

  const stateOf = (item: HandoffItem): SegmentState => changed.has(item.id) ? "changed" : item.status === "confirmed" ? "ok" : item.status === "deviated" ? "mismatch" : item.status === "reported" ? "built" : "todo";
  const states = launchItems.map(stateOf);
  const count = (state: SegmentState) => states.filter(s => s === state).length;
  const campaign = launchItems.find(item => item.planned_kind === "campaign");
  const approved = when(stale.approved_at, timezone), edited = when(stale.changed_at, timezone);
  const assetsHref = campaignPath(brandId, campaignId, {tab: "assets"});

  return (
    <div className="flex max-w-[1260px] flex-col gap-4">
      <FlowHeader
        steps={STEPS}
        current={1}
        title="到平台完成"
        purpose="方案改過，先決定用哪一版"
        context={<>{campaign && <CampaignChip objective="other" name={campaign.name} />}<span>首次上架・{launchItems.length} 項</span></>}
      />
      <ResultHero tone="warn" title={`核准後方案又改過 ${stale.diff.length} 處，清單先停在這裡`} note={[approved && `核准於 ${approved}`, edited && `${edited} 修改`].filter(Boolean).join("・") || undefined} />

      <section className="surface px-[22px] py-5" aria-label="核准時 → 現在">
        <div className="mb-1 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-[15px] font-semibold">核准時 → 現在</h2>
          <Chip>其他 {stale.unchanged_count} 項沒有變</Chip>
        </div>
        {stale.diff.map((row, i) => {
          const index = launchItems.findIndex(item => item.id === row.item_id);
          const ad = row.field === "material" ? plannedAd(row) : undefined;
          const next = ad?.assignment_status === "stale" ? materials?.ready_placements.find(p => p.id === ad.placement_id) : undefined;
          return (
            <div key={`${row.kind}:${row.item_id ?? row.name}:${row.field}:${i}`}>
              <DiffRow
                field={row.field_label}
                item={`${KIND[row.kind] ?? row.kind}・${index >= 0 ? `#${index + 1}` : row.name ?? "未命名"}`}
                before={valueOf(row.before)}
                after={valueOf(row.after)}
                beforeLabel={approved ? `核准時・${approved.slice(0, 5)}` : "核准時"}
                afterLabel={edited ? `現在・${edited.slice(0, 5)} 改` : "現在"}
              />
              {ad?.assignment_status === "stale" && (
                <div className="flex flex-wrap items-center justify-end gap-2 pb-3 text-xs text-warning">
                  <span>{next ? `素材已修訂，換成第 ${next.revision} 版才能重新核准` : "素材已修訂，先到素材頁指派確認過的版本"}</span>
                  {next
                    ? <Button size="sm" variant="outline" busy={Boolean(busy)} onClick={() => void reassign(ad.id, next.id, next.revision)}>{busy === "assign" ? "換版中…" : `改用第 ${next.revision} 版`}</Button>
                    : <Button size="sm" variant="outline" asChild><Link to={assetsHref}>到素材頁指派</Link></Button>}
                </div>
              )}
            </div>
          );
        })}
        {materialError && <p role="alert" className="pt-2 text-xs text-destructive">{materialError}</p>}
      </section>

      <section className="surface px-[22px] py-5" aria-label="核對進度">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-[15px] font-semibold">{count("ok")}／{launchItems.length} 已核對</h2>
          <span className="text-sm text-muted-foreground">已核對的會保留結果</span>
        </div>
        <ProgressSegments segments={launchItems.map((item, i) => ({ key: item.id, state: states[i], title: item.name }))} label={`${count("ok")}／${launchItems.length} 已核對`} />
        <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-muted-foreground">
          <span><i aria-hidden="true" className="mr-1.5 inline-block size-2 rounded-[2px] bg-success" />已核對 {count("ok")}</span>
          <span><i aria-hidden="true" className="mr-1.5 inline-block size-2 rounded-[2px] bg-warning" />有變更 {count("changed")}</span>
          <span><i aria-hidden="true" className="mr-1.5 inline-block size-2 rounded-[2px] bg-chart-soft" />已建好待讀回 {count("built")}</span>
          {count("mismatch") > 0 && <span><i aria-hidden="true" className="mr-1.5 inline-block size-2 rounded-[2px] bg-warning/80" />不符 {count("mismatch")}</span>}
          <span><i aria-hidden="true" className="mr-1.5 inline-block size-2 rounded-[2px] bg-muted" />待操作 {count("todo")}</span>
        </div>
        <div className="mt-2">
          {launchItems.map((item, i) => {
            const state = states[i];
            return (
              <TodoRow key={item.id} no={i + 1} done={state === "ok"} action={state === "ok" ? <Chip tone="ok">✓ 已核對</Chip> : state === "changed" ? <Chip tone="warn">有變更</Chip> : <Chip>等重新核准</Chip>}>
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <Chip>{KIND[item.planned_kind] ?? item.planned_kind}</Chip>
                  <span className="min-w-0 font-medium [overflow-wrap:anywhere]">{item.name}</span>
                </div>
              </TodoRow>
            );
          })}
        </div>
      </section>

      {sheet && stale.revertible && (
        <div ref={sheetRef}>
          <ConfirmSheet
            variant="revert"
            title="改回核准時的設定？"
            actions={<>
              <Button variant="ghost" busy={Boolean(busy)} onClick={() => setSheet(false)}>取消</Button>
              <WarnButton busy={Boolean(busy)} onClick={() => void decide("revert")}>{busy === "revert" ? "改回中…" : "改回，沿用原本的核准"}</WarnButton>
            </>}
          >
            {stale.diff.map((row, i) => <div key={`${row.field}:${i}`}>{row.field_label}：{printed(row.after)} → {printed(row.before)}</div>)}
          </ConfirmSheet>
        </div>
      )}

      <ActionBar hint={needsMaterial.length ? "先換成確認過的素材版本，才能重新核准" : "重新核准不會改動平台"}>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {stale.revertible
            ? <Button variant="outline" busy={Boolean(busy)} onClick={() => setSheet(true)}>改回核准時的設定</Button>
            : <p className="max-w-[360px] text-xs text-warning">{stale.revert_blocker ?? "這些變更無法自動改回；請用現在的方案重新核准。"}</p>}
          <Button busy={Boolean(busy)} disabledReason={needsMaterial.length > 0 ? "先補齊變更後需要的素材" : undefined} onClick={() => void decide("reapprove")}>{busy === "reapprove" ? "重新核准中…" : "用現在的方案重新核准 →"}</Button>
        </div>
      </ActionBar>
    </div>
  );
}
