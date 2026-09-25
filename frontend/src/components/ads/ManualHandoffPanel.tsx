import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import { Textarea } from "@/components/layout/ui/textarea";
import { useWorkspace } from "@/components/layout/WorkspaceContext";
import { existingCampaigns, externalView, type NativeEntity, type SourceAccount } from "@/lib/adsExternalApi";
import { checkHandoff, createNewAdHandoff, getHandoff, HandoffRequestRejected, reconsiderHandoff, refreshHandoffSources, reportHandoff, type HandoffIdentity, type HandoffItem, type HandoffWorkspace, type NewAdHandoffRequest } from "@/lib/adsHandoffApi";
import { formatSyncTime } from "@/lib/format";
import { currentBudgetMonth } from "./MonthlyBudgetPanel";
import { Disclosure } from "./patterns/Disclosure";
import { LaunchStalePanel, type LaunchOutcome } from "./LaunchStalePanel";

type Props = {
  brandId: string; campaignId: string; mode?: "all" | "items" | "new-ad"; refreshKey?: number;
  /** Tells the host whether this handoff has anything to verify (items or a stale launch), so the host never
   * shows its own "nothing to verify" state beside a handoff that lists items. */
  onHandoffWork?: (hasWork: boolean) => void;
};
const states: Record<string, string> = { pending: "待操作", reported: "已回報，待讀回", confirmed: "設定已核對", deviated: "設定有差異", unknown: "尚未能確認", stale: "需重新確認" };
const materials: Record<string, string> = { unknown: "未知", user_verified: "使用者人工核對", media_verified: "媒體來源已核對" };
const kinds: Record<string, string> = { campaign: "活動", group: "投放組", adset: "廣告組", ad: "廣告" };
const fieldLabels: Record<string, string> = { utm: "網址追蹤標記", bidding: "出價設定", tracking: "追蹤設定", attribution: "成效歸因期間", landing_url: "導流網址", audience_source: "受眾來源", audience_window: "受眾期間", optimization_event: "最佳化事件", audience_exclusions: "排除受眾", objective: "投放目標", budget_type: "預算類型", budget_amount: "預算金額", start_date: "開始日期", end_date: "結束日期", copy_text: "文案", copy: "核准文案", material_required: "需要素材核對", manual_settings: "人工設定", title: "標題", body: "內文", description: "說明", targeting: "受眾", bid_strategy: "出價方式", placements: "版位", status: "投放狀態", material: "圖片／影片", parent: "上層對應" };
function fieldLabel(field: string) {
  if (field.startsWith("人工設定：")) return fieldLabels[field.slice(5)] ?? "其他人工設定";
  return fieldLabels[field] ?? (field.startsWith("文案：") ? `文案：${fieldLabels[field.slice(3)] ?? "其他文字"}` : /[\u4e00-\u9fff]/.test(field) ? field : "相關平台設定");
}
function expectedText(value: unknown): string { if (value == null) return "尚未提供"; if (typeof value === "boolean") return value ? "是" : "否"; if (typeof value !== "object") return String(value); return Object.entries(value).filter(([key]) => key in fieldLabels).map(([key, val]) => `${fieldLabels[key]}：${expectedText(val)}`).join("；") || "請依原計畫核對詳細設定"; }
const message = (error: unknown) => error instanceof Error ? error.message : "結果尚未確認，請重試核對。";
const nativeKey = (node: Pick<NativeEntity, "platform" | "source_account" | "native_kind" | "native_id">) => [node.platform, node.source_account, node.native_kind, node.native_id].join(":");
const mergeNodes = (nodes: NativeEntity[]) => [...new Map(nodes.map(node => [nativeKey(node), node])).values()];

export function ManualHandoffPanel(props: Props) {
  const { scope } = useWorkspace();
  return <Panel key={`${scope}:${props.brandId}:${props.campaignId}`} {...props} scope={scope} />;
}

function Panel({ brandId, campaignId, scope, mode = "all", refreshKey = 0, onHandoffWork }: Props & { scope: string }) {
  const [data, setData] = useState<HandoffWorkspace | null>(null);
  const [nodes, setNodes] = useState<NativeEntity[]>([]);
  const [roots, setRoots] = useState<NativeEntity[]>([]);
  const [sources, setSources] = useState<SourceAccount[]>([]);
  const [source, setSource] = useState("");
  const [rootCursor, setRootCursor] = useState<string | null>(null);
  const [entityCursor, setEntityCursor] = useState<string | null>(null);
  const [windowRange, setWindowRange] = useState<{ start: string; end: string }>();
  const [error, setError] = useState("");
  const [candidateError, setCandidateError] = useState("");
  const [syncNotice, setSyncNotice] = useState("");
  const [reload, setReload] = useState(0);
  const [busy, setBusy] = useState("");
  const [activeItemId, setActiveItemId] = useState("");
  const [launchOutcome, setLaunchOutcome] = useState<LaunchOutcome | null>(null);
  const lifetime = useRef(new AbortController());
  useEffect(() => { lifetime.current = new AbortController(); return () => lifetime.current.abort(); }, []);
  const hasWork = data ? data.items.length > 0 || data.launch_stale !== null : null;
  const reportWork = useRef(onHandoffWork);
  reportWork.current = onHandoffWork;
  useEffect(() => { if (hasWork !== null) reportWork.current?.(hasWork); }, [hasWork]);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    getHandoff(brandId, campaignId, controller.signal).then(value => { if (!controller.signal.aborted) setData(value); }).catch(err => { if (!controller.signal.aborted) setError(message(err)); });
    if (mode !== "new-ad") {
      externalView(brandId, campaignId, {}, controller.signal).then(value => {
        if (controller.signal.aborted) return;
        setNodes(value.entities); setEntityCursor(value.next_entity_cursor); setWindowRange(value.window);
      }).catch(err => { if (!controller.signal.aborted) setCandidateError(message(err)); });
      existingCampaigns(brandId, {}, controller.signal).then(value => {
        if (controller.signal.aborted) return;
        setSources(value.sources); setSource(`${value.platform ?? ""}:${value.source_account ?? ""}`);
        setRoots(value.items.map(item => item.snapshot)); setRootCursor(value.next_cursor);
      }).catch(err => { if (!controller.signal.aborted) setCandidateError(message(err)); });
    }
    return () => controller.abort();
  }, [brandId, campaignId, mode, reload, refreshKey]);

  async function loadSource(value: string, cursor?: string) {
    const account = sources.find(row => `${row.platform}:${row.account_id}` === value);
    if (!account || busy) return;
    const signal = lifetime.current.signal; setBusy("sources"); setCandidateError("");
    if (!cursor) { setSource(value); setRoots([]); setRootCursor(null); }
    try {
      const result = await existingCampaigns(brandId, { platform: account.platform, source_account: account.account_id, ...(cursor ? { cursor } : {}) }, signal);
      if (!signal.aborted) { setRoots(old => mergeNodes([...(cursor ? old : []), ...result.items.map(item => item.snapshot)])); setRootCursor(result.next_cursor); }
    } catch (err) { if (!signal.aborted) setCandidateError(message(err)); }
    finally { if (!signal.aborted) setBusy(""); }
  }
  async function moreEntities() {
    if (!entityCursor || busy) return;
    const signal = lifetime.current.signal; setBusy("sources");
    try {
      const result = await externalView(brandId, campaignId, { entity_cursor: entityCursor, ...windowRange }, signal);
      if (!signal.aborted) { setNodes(old => mergeNodes([...old, ...result.entities])); setEntityCursor(result.next_entity_cursor); }
    } catch (err) { if (!signal.aborted) setCandidateError(message(err)); }
    finally { if (!signal.aborted) setBusy(""); }
  }
  async function act(item: HandoffItem, identity?: HandoffIdentity, reason?: string) {
    if (busy) return;
    const signal = lifetime.current.signal; setBusy(item.id); setError("");
    try {
      const result = reason ? await reconsiderHandoff(brandId, campaignId, item.id, reason, signal) : identity ? await checkHandoff(brandId, campaignId, item.id, identity, signal) : await reportHandoff(brandId, campaignId, item.id, signal);
      if (!signal.aborted) setData(old => old ? { ...old, items: old.items.map(row => row.id === result.id ? result : row) } : old);
    } catch (err) { if (!signal.aborted) setError(message(err)); }
    finally { if (!signal.aborted) setBusy(""); }
  }
  async function refreshSources() {
    if (busy) return;
    const signal = lifetime.current.signal; setBusy("sync"); setCandidateError(""); setSyncNotice("");
    try { await refreshHandoffSources(brandId, campaignId, signal); if (!signal.aborted) setSyncNotice("來源讀取已排入，稍後按「重新讀取」查看候選。尚未確認的物件仍保留待核對。"); }
    catch (err) { if (!signal.aborted) setCandidateError(message(err)); }
    finally { if (!signal.aborted) setBusy(""); }
  }
  const candidates = mergeNodes([...nodes, ...roots]);
  const selectedSource = sources.find(row => `${row.platform}:${row.account_id}` === source);
  // F28 "Stale launch": while the approved launch no longer matches the plan, its items wait for a decision
  // (re-approve or revert) in LaunchStalePanel; per-item checks stay available only for other handoffs.
  const stale = mode !== "new-ad" ? data?.launch_stale ?? null : null;
  const workItems = (stale ? data?.items.filter(item => item.change_set_id !== stale.change_set_id) : data?.items) ?? [];
  const pendingItems = workItems.filter(item => item.status !== "confirmed");
  const confirmedItems = workItems.filter(item => item.status === "confirmed");
  const activeItem = pendingItems.find(item => item.id === activeItemId) ?? pendingItems[0];
  const renderItem = (item: HandoffItem) => <HandoffRow key={`${item.id}:${item.entity_id ?? ""}:${data?.items.find(row => row.id === item.parent_item_id)?.entity_id ?? ""}:${source}`} item={item} parent={data?.items.find(row => row.id === item.parent_item_id)} nodes={candidates} source={selectedSource} busy={Boolean(busy)} onReport={() => void act(item)} onCheck={identity => void act(item, identity)} onReconsider={reason => void act(item, undefined, reason)} />;
  const regular = !stale || workItems.length > 0;
  return <section className="space-y-4" aria-label="人工交接與平台核對">
    {launchOutcome && <p role={launchOutcome.tone === "error" ? "alert" : "status"} className={launchOutcome.tone === "error" ? "rounded-lg bg-destructive/5 p-3 text-sm text-destructive" : "rounded-lg bg-success/10 p-3 text-sm text-success"}>{launchOutcome.text}</p>}
    {data && stale && <LaunchStalePanel brandId={brandId} campaignId={campaignId} stale={stale} items={data.items}
      onDecided={(value, outcome) => { setData(value); setLaunchOutcome(outcome); setReload(n => n + 1); }}
      onReload={outcome => { setLaunchOutcome(outcome ?? null); setReload(n => n + 1); }} />}
    {regular && <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-lg font-semibold">人工交接與平台核對</h2><p className="text-sm text-muted-foreground">平台操作完成後，逐項回報並讀回核對；找不到物件時保留待核對，不要再建立一次。</p></div><Button variant="outline" disabled={Boolean(busy)} onClick={() => { setCandidateError(""); setLaunchOutcome(null); setReload(n => n + 1); }}>重新讀取</Button></div>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {!data && !error && <p role="status">讀取交接內容…</p>}
    {data && <>
      {regular && <p className="rounded-lg border border-primary/20 bg-primary/5 p-3 text-sm">{data.notice}</p>}
      {mode !== "new-ad" && regular && <>
        <div className="flex flex-wrap items-end gap-3">
          {sources.length > 0 && <label className="text-sm">候選來源帳戶<select className="mt-1 block w-full" value={source} disabled={Boolean(busy)} onChange={e => void loadSource(e.target.value)}>{sources.map(row => <option key={`${row.platform}:${row.account_id}`} value={`${row.platform}:${row.account_id}`}>{row.label} · {row.name || row.account_id}</option>)}</select></label>}
          {rootCursor && <Button variant="outline" disabled={Boolean(busy)} onClick={() => void loadSource(source, rootCursor)}>更多平台活動</Button>}
          {entityCursor && <Button variant="outline" disabled={Boolean(busy)} onClick={() => void moreEntities()}>更多已讀回物件</Button>}
          <Button variant="outline" disabled={Boolean(busy)} onClick={() => void refreshSources()}>更新平台候選</Button>
        </div>
        {syncNotice && <p role="status" className="text-sm text-muted-foreground">{syncNotice}</p>}
        {candidateError && <p role="alert" className="text-sm text-warning">候選清單暫時不完整：{candidateError}。可重讀或展開進階欄位核對識別。</p>}
        {data.items_truncated && <p className="text-sm text-warning">交接項目超過本次顯示範圍，目前清單不代表全部完成。</p>}
        {!workItems.length && <p className="text-sm text-muted-foreground">核准首次投放或新增廣告清單後，這裡會列出逐項交接內容。</p>}
        {workItems.length > 0 && <p className="text-sm font-medium">{pendingItems.length} 項待處理 · {confirmedItems.length} 項設定已核對</p>}
        {pendingItems.length > 1 && <label className="block text-sm font-medium">選擇這次要核對的項目<select className="mt-2 block w-full" value={activeItem?.id ?? ""} disabled={Boolean(busy)} onChange={event => setActiveItemId(event.target.value)}>{pendingItems.map(item => <option key={item.id} value={item.id}>{item.name} · {states[item.status] ?? "待確認"}</option>)}</select><span className="mt-1 block text-xs font-normal text-muted-foreground">一次處理一項；其他項目的進度會保留。上層物件須先讀回，才能核對下層。</span></label>}
        {activeItem && renderItem(activeItem)}
        {confirmedItems.length > 0 && <Disclosure label={`查看已核對的 ${confirmedItems.length} 項與證據`}><div className="space-y-3">{confirmedItems.map(renderItem)}</div></Disclosure>}
      </>}
      {mode !== "items" && <NewAdForm key={`${scope}:${brandId}:${campaignId}`} brandId={brandId} campaignId={campaignId} scope={scope} data={data} />}
    </>}
  </section>;
}

function HandoffRow({ item, parent, nodes, source, busy, onReport, onCheck, onReconsider }: {
  item: HandoffItem; parent?: HandoffItem; nodes: NativeEntity[]; source?: SourceAccount; busy: boolean;
  onReport: () => void; onCheck: (value: HandoffIdentity) => void; onReconsider: (reason: string) => void;
}) {
  const [identity, setIdentity] = useState<HandoffIdentity>({ platform: item.platform ?? parent?.platform ?? source?.platform ?? "", source_account: item.source_account ?? parent?.source_account ?? source?.account_id ?? "", native_kind: item.native_kind ?? "", native_id: item.native_id ?? "", user_verified: false });
  const [selected, setSelected] = useState("");
  const [reconsiderReason, setReconsiderReason] = useState("");
  const immutable = Boolean(item.entity_id);
  const available = nodes.filter(node => (!identity.platform || node.platform === identity.platform) && (!identity.source_account || node.source_account === identity.source_account) && (item.planned_kind === "ad" ? node.native_kind === "ad" : item.planned_kind === "campaign" ? !node.parent_native_id : node.native_kind !== "ad" && Boolean(node.parent_native_id)) && (!parent?.native_id || node.parent_native_id === parent.native_id));
  const missingParent = Boolean(item.parent_item_id && !parent?.entity_id);
  const ready = identity.platform && identity.source_account && identity.native_kind && identity.native_id;
  return <article className="surface" aria-label={`交接 ${item.name}`}>
    <div className="surface-header flex flex-wrap items-center justify-between gap-2"><h3>{item.name} <span className="text-xs font-normal text-muted-foreground">{kinds[item.planned_kind] ?? item.planned_kind}</span></h3><span className="rounded-full bg-muted px-3 py-1 text-xs">{states[item.status] ?? item.status}</span></div>
    <div className="surface-body space-y-4">
      {item.expected_parent_name && <p className="text-sm text-muted-foreground">上層：{item.expected_parent_name}</p>}
      <div className="grid gap-3 sm:grid-cols-3">
        <Evidence label="物件存在" value={item.entity_exists ? "已讀回" : "尚未確認"} />
        <Evidence label="設定相符" value={item.setting_matches === true ? "相符" : item.setting_matches === false ? "有差異" : "未知"} />
        <Evidence label="圖片／影片等價" value={materials[item.material_evidence] ?? "未知"} />
      </div>
      <p className="text-xs text-muted-foreground">使用者回報：{item.reported_at ? formatSyncTime(item.reported_at) : "尚未回報"} · 最近讀回：{item.observed_at ? formatSyncTime(item.observed_at) : "尚未讀回"} · 實際投遞與生效時間：尚未確認</p>
      {item.evidence_json.message && <p className="text-sm text-muted-foreground">{item.evidence_json.message}</p>}
      {item.evidence_json.unknown_fields?.length ? <Disclosure label={`${item.evidence_json.unknown_fields.length} 項設定尚待確認，查看原因`}><p className="text-sm text-warning">目前讀取介面無法核對以下設定：{item.evidence_json.unknown_fields.map(field => fieldLabel(field)).join("、")}。可保留本次交接，補齊平台資料後重新核對；不需要重建廣告。</p></Disclosure> : null}
      {item.evidence_json.deviated_fields?.length ? <p className="text-sm text-destructive">差異：{item.evidence_json.deviated_fields.map(field => fieldLabel(field)).join("、")}</p> : null}
      <Disclosure label="核准內容與操作識別">
        <dl className="space-y-2 text-sm">{Object.entries(item.expected_json).filter(([key]) => key in fieldLabels).map(([key, value]) => <div key={key}><dt className="font-medium">{fieldLabels[key]}</dt><dd className="whitespace-pre-wrap break-words text-muted-foreground">{expectedText(value)}</dd></div>)}</dl>
      </Disclosure>
      {!immutable && <label className="block text-sm">選擇平台候選物件<select className="mt-1 w-full" value={selected} disabled={busy || missingParent} onChange={e => { setSelected(e.target.value); const node = available.find(row => nativeKey(row) === e.target.value); if (node) setIdentity({ platform: node.platform, source_account: node.source_account, native_kind: node.native_kind, native_id: node.native_id, user_verified: false }); }}><option value="">選擇後再讀回核對</option>{available.map(node => <option key={nativeKey(node)} value={nativeKey(node)}>{node.name || "未命名"} · {node.native_label || node.native_kind} · {node.native_id}</option>)}</select></label>}
      {immutable && <p className="text-sm">已對應：{item.platform} · 帳戶 {item.source_account} · {item.native_id}</p>}
      <Disclosure label="進階：手填平台識別">
        <p className="mb-3 text-xs text-muted-foreground">候選尚未出現時，可填入平台上的確切識別。這些欄位用於唯讀核對，不會新建平台物件。</p>
        <div className="grid gap-3 sm:grid-cols-2">{([ ["platform", "平台代碼"], ["source_account", "來源帳戶"], ["native_kind", "物件層級"], ["native_id", "平台物件識別"] ] as const).map(([key, label]) => <label key={key} className="text-sm">{label}<Input value={identity[key]} disabled={busy || immutable || missingParent} onChange={e => { setSelected(""); setIdentity(old => ({ ...old, [key]: e.target.value, user_verified: false })); }} /></label>)}</div>
      </Disclosure>
      {item.planned_kind === "ad" && <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={identity.user_verified} disabled={busy} onChange={e => setIdentity(old => ({ ...old, user_verified: e.target.checked }))} />我已人工比較這則廣告的圖片／影片與核准素材（只記人工核對）</label>}
      {missingParent && <p className="text-sm text-warning">請先核對上層物件，再選擇這一項。</p>}
      <div className="flex flex-wrap gap-2"><Button variant="outline" disabled={busy || Boolean(item.reported_at)} onClick={onReport}>{item.reported_at ? "已回報人工操作" : "我已到平台操作"}</Button><Button disabled={busy || !ready || missingParent || item.status === "stale"} onClick={() => onCheck({ ...identity, platform: identity.platform.trim(), source_account: identity.source_account.trim(), native_kind: identity.native_kind.trim(), native_id: identity.native_id.trim() })}>{item.status === "unknown" ? "重新讀回核對" : "讀回並核對此物件"}</Button></div>
      {item.entity_id && item.native_kind === "ad" && item.status !== "stale" && <Disclosure label="已停用的廣告：重新檢視方案">
        <p className="mb-3 text-sm text-muted-foreground">若你已在平台停用這則廣告，可讀回確認後重審新方案。仍啟用、無法讀回或只有設定差異時，都不會開放重建。</p>
        <label className="block text-sm">重審原因<Textarea value={reconsiderReason} disabled={busy} onChange={e => setReconsiderReason(e.target.value)} maxLength={2000} /></label>
        <Button className="mt-3" variant="outline" disabled={busy || !reconsiderReason.trim()} onClick={() => onReconsider(reconsiderReason.trim())}>核對已停用，重審新方案</Button>
      </Disclosure>}
    </div>
  </article>;
}
function Evidence({ label, value }: { label: string; value: string }) { return <div className="rounded-lg border border-border p-3"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-1 text-sm font-medium">{value}</p></div>; }

type Pending = { request: NewAdHandoffRequest; changeSetId?: string };
function NewAdForm({ brandId, campaignId, scope, data }: { brandId: string; campaignId: string; scope: string; data: HandoffWorkspace }) {
  const navigate = useNavigate();
  const storageKey = `ads-new-ad-handoff:${scope}:${brandId}:${campaignId}`;
  const [pending, setPending] = useState<Pending | null>(() => { try { const saved = JSON.parse(sessionStorage.getItem(storageKey) ?? "null") as Pending | null; return saved?.request?.operation_id ? saved : null; } catch { return null; } });
  const [title, setTitle] = useState(pending?.request.title ?? "");
  const [month, setMonth] = useState(pending?.request.month ?? currentBudgetMonth());
  const [placementId, setPlacementId] = useState(pending?.request.placement_id ?? "");
  const [destination, setDestination] = useState(pending?.request.destination_entity_id ?? "");
  const [reason, setReason] = useState(pending?.request.reason ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const lifetime = useRef(new AbortController());
  useEffect(() => { lifetime.current = new AbortController(); return () => lifetime.current.abort(); }, []);
  const groups = data.destinations.filter(node => node.native_kind !== "ad" && node.parent_native_id);
  const locked = busy || Boolean(pending);
  const changeHref = (id: string) => `/brands/${encodeURIComponent(brandId)}/ads/campaigns/${encodeURIComponent(campaignId)}?tab=changes&change=${encodeURIComponent(id)}`;
  async function save() {
    if (busy || pending?.changeSetId) return;
    const placement = data.ready_placements.find(row => row.id === placementId);
    if (!pending && (!placement || !title.trim() || !reason.trim() || !destination || !/^\d{4}-\d{2}$/.test(month))) { setError("請選擇已確認素材、既有投放組，並填寫新廣告名稱、月份與理由。"); return; }
    const request = pending?.request ?? { operation_id: crypto.randomUUID(), title: title.trim(), month, placement_id: placement!.id, revision: placement!.revision, destination_entity_id: destination, reason: reason.trim() };
    const signal = lifetime.current.signal;
    try { sessionStorage.setItem(storageKey, JSON.stringify({ request })); } catch { setError("無法保存操作識別，請允許此分頁儲存後再試，尚未送出。"); return; }
    setPending({ request }); setBusy(true); setError("");
    try {
      const result = await createNewAdHandoff(brandId, campaignId, request, signal);
      if (signal.aborted) return;
      const receipt = { request, changeSetId: result.id }; setPending(receipt); sessionStorage.setItem(storageKey, JSON.stringify(receipt));
      navigate(changeHref(result.id));
    } catch (err) {
      if (signal.aborted) return;
      if (err instanceof HandoffRequestRejected) { sessionStorage.removeItem(storageKey); setPending(null); }
      setError(message(err));
    } finally { if (!signal.aborted) setBusy(false); }
  }
  return <section className="surface" aria-label="新增獨立廣告">
    <div className="surface-header"><div><h3>新增 B2，保留原廣告</h3><p className="text-sm text-muted-foreground">選擇已確認素材，先建立待核准清單；核准後才由你到平台新增另一則廣告。</p></div></div>
    <div className="surface-body space-y-4">
      {pending && <p role="status" className="rounded-md bg-warning/10 p-3 text-sm">{pending.changeSetId ? "清單已保存，請前往檢視並核准。" : "上次保存結果尚未確認，重試會沿用同一份內容與操作識別，請勿重建平台廣告。"}</p>}
      {!data.ready_placements.length && !pending && <p className="text-sm text-muted-foreground">尚無已確認且原檔可用的素材安排，請先在素材頁確認版本。</p>}
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm">新廣告名稱<Input value={title} maxLength={200} disabled={locked} onChange={e => setTitle(e.target.value)} /></label>
        <label className="text-sm">預算月份<Input type="month" value={month} disabled={locked} onChange={e => setMonth(e.target.value)} /></label>
        <label className="text-sm">已確認素材<select className="mt-1 block w-full" value={placementId} disabled={locked} onChange={e => { setPlacementId(e.target.value); const selectedPlacement = data.ready_placements.find(row => row.id === e.target.value); setDestination(groups.some(row => row.id === selectedPlacement?.destination_entity_id) ? selectedPlacement!.destination_entity_id! : ""); }}><option value="">請選擇</option>{data.ready_placements.map(row => <option key={row.id} value={row.id}>{row.filename} · 版本 {row.revision}</option>)}</select></label>
        <label className="text-sm">加入既有投放組<select className="mt-1 block w-full" value={destination} disabled={locked} onChange={e => setDestination(e.target.value)}><option value="">請選擇</option>{groups.map(row => <option key={row.id} value={row.id}>{row.name || row.native_id} · {row.platform} · {row.source_account}</option>)}</select></label>
      </div>
      {data.destinations_truncated && <p className="text-sm text-warning">本次未列出全部投放組，找不到時請回投放中心確認來源，勿任選其他對象。</p>}
      <label className="block text-sm">新增理由<Textarea value={reason} maxLength={2000} disabled={locked} onChange={e => setReason(e.target.value)} /></label>
      <p className="text-xs text-muted-foreground">沿用既有父層預算仍須在核准時核對，不能假定新增廣告不增加花費。</p>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {pending?.changeSetId ? <div className="flex flex-wrap gap-2"><Button asChild><Link to={changeHref(pending.changeSetId)}>前往檢視並核准</Link></Button><Button variant="outline" onClick={() => { sessionStorage.removeItem(storageKey); setPending(null); setTitle(""); setPlacementId(""); setDestination(""); setReason(""); setError(""); }}>建立另一份新增清單</Button></div> : <Button disabled={busy || (!pending && (!data.ready_placements.length || !groups.length))} onClick={() => void save()}>{busy ? "保存中…" : pending ? "重試同一份新增清單" : "保存清單，檢視並核准"}</Button>}
    </div>
  </section>;
}
