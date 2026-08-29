import { useEffect, useState, type ReactNode } from "react";
import { X } from "lucide-react";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { Pager } from "@/components/layout/Pager";
import { SidePanel } from "@/components/layout/SidePanel";
import { Skeleton } from "@/components/layout/Skeleton";
import { StatBig } from "@/components/layout/StatBig";
import { formatCurrency } from "@/lib/format";
import {
  createChannelEntry,
  createPolicyChange,
  fetchOrders,
  HAND_ENTRY_CHANNEL_TYPES,
  importOrdersFile,
  saveSkuCost,
  setOrderAttribution,
  type OrdersPageData,
  type SkuMargin,
} from "@/lib/ordersApi";
import { useFormSubmit } from "@/lib/useFormSubmit";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: OrdersPageData };

type Panel =
  | { kind: "import" }
  | { kind: "sku-cost"; sku: string }
  | { kind: "policy-change" }
  | { kind: "channel-entry" }
  | null;

function displayNumber(value: number | null): string {
  return value === null ? "累積中" : value.toLocaleString("zh-TW");
}

function displayPercent(value: number | null): string {
  return value === null ? "累積中" : `${Math.round(value * 100)}%`;
}

function displayMargin(value: SkuMargin["margin"]): string {
  return value === null ? "未登記成本" : formatCurrency(value);
}

/** 訂單總覽：既有訂單統計與五個寫入動作都在同一張頁面完成。 */
export function OrdersPage({ brandId }: { brandId: string }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [panel, setPanel] = useState<Panel>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  function load(page = 1) {
    setState({ status: "loading" });
    fetchOrders(brandId, page)
      .then((data) => setState({ status: "ready", data }))
      .catch((err: unknown) => setState({ status: "error", message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。" }));
  }

  function refreshAfterSave(message: string) {
    const page = state.status === "ready" ? state.data.orders.page : 1;
    setPanel(null);
    setSuccessMessage(message);
    load(page);
  }

  useEffect(() => {
    setPanel(null);
    setSuccessMessage(null);
    load();
  }, [brandId]);

  let content: ReactNode;
  if (state.status === "loading") {
    content = <div className="flex flex-col gap-3"><div className="grid grid-cols-2 gap-3 md:grid-cols-5">{Array.from({ length: 5 }, (_, index) => <Skeleton key={index} className="h-24" />)}</div><Skeleton className="h-64 w-full" /></div>;
  } else if (state.status === "error") {
    content = <EmptyState title="讀取失敗" description={state.message} onAction={() => load()} actionLabel="重新載入" />;
  } else {
    const { brand, summary, orders, policy_changes: policyChanges, channel_entries: channelEntries } = state.data;
    const noData = !summary.has_history && orders.total === 0;
    const pageCount = Math.ceil(orders.total / orders.page_size);
    content = <>
      <div className="flex items-start justify-between gap-4">
        <div className="flex flex-col gap-1">
          <Breadcrumb items={[{ label: "跨品牌總覽", href: "/" }, { label: brand.name, href: `/brands/${brandId}` }, { label: "訂單與顧客" }]} />
          <h1 className="font-display text-2xl text-foreground">訂單與顧客</h1>
          <p className="text-sm text-muted-foreground">統計區間 {summary.since} ～ {summary.until}（最近 30 天）</p>
        </div>
        <button type="button" onClick={() => setPanel({ kind: "import" })} className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90">匯入訂單檔</button>
      </div>
      {successMessage && <p role="status" className="rounded-md border border-success/40 bg-success/10 px-3 py-2 text-sm text-foreground">{successMessage}</p>}
      {noData ? <EmptyState title="還沒有訂單資料" description="把 EasyStore 訂單匯出檔拖進來，這頁就會出現營收、毛利與回購率。" /> : <>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          <StatBig value={formatCurrency(summary.net_revenue)} label="實收營收" />
          <StatBig value={displayNumber(summary.order_count)} label="訂單數" />
          <StatBig value={formatCurrency(summary.average_order_value)} label="平均客單價" />
          <StatBig value={`${summary.new_customers}／${summary.existing_customers}`} label="新客／舊客" />
          <StatBig value={displayPercent(summary.repurchase_rate)} label="回購率" />
        </div>
        <section className="flex flex-col gap-3">
          <h2 className="font-display text-xl text-foreground">逐項商品毛利</h2>
          {summary.sku_margins.length === 0 ? <p className="text-sm text-muted-foreground">這段期間還沒有可統計的 SKU 資料。</p> : <Table><thead className="bg-muted text-muted-foreground"><tr><Header>SKU</Header><Header>數量</Header><Header>營收</Header><Header>單位成本</Header><Header>毛利</Header><Header>動作</Header></tr></thead><tbody>{summary.sku_margins.map((item) => <tr key={item.sku} className="border-t border-border"><Cell>{item.sku}</Cell><Cell>{displayNumber(item.quantity)}</Cell><Cell>{formatCurrency(item.revenue)}</Cell><Cell>{item.unit_cost === null ? "未登記成本" : formatCurrency(item.unit_cost)}</Cell><Cell>{displayMargin(item.margin)}</Cell><Cell><TextButton onClick={() => setPanel({ kind: "sku-cost", sku: item.sku })}>登記成本</TextButton></Cell></tr>)}</tbody></Table>}
        </section>
        <section className="flex flex-col gap-3">
          <h2 className="font-display text-xl text-foreground">最近訂單</h2>
          <Table><thead className="bg-muted text-muted-foreground"><tr><Header>訂單編號</Header><Header>日期</Header><Header>金額</Header><Header>訂單狀態</Header><Header>優惠碼</Header><Header>來源</Header></tr></thead><tbody>{orders.items.map((item) => <tr key={item.id} className="border-t border-border"><Cell>{item.order_number}</Cell><Cell>{item.order_date ?? "—"}</Cell><Cell>{formatCurrency(item.total_amount)}</Cell><Cell>{item.order_status ?? "—"}</Cell><Cell>{item.voucher_code ?? "—"}</Cell><Cell><AttributionButton brandId={brandId} orderId={item.id} excluded={item.attribution_override === "excluded"} onSaved={refreshAfterSave} /></Cell></tr>)}</tbody></Table>
          <Pager page={orders.page} pageCount={pageCount} totalCount={orders.total} onChange={load} />
        </section>
      </>}
      <section className="flex flex-col gap-3">
        <SectionHeading title="口徑變更紀錄" onAdd={() => setPanel({ kind: "policy-change" })} />
        {policyChanges.length === 0 ? <p className="text-sm text-muted-foreground">還沒有口徑變更紀錄。</p> : <Table><thead className="bg-muted text-muted-foreground"><tr><Header>類型</Header><Header>變更日</Header><Header>說明</Header></tr></thead><tbody>{policyChanges.map((item) => <tr key={`${item.policy_type}-${item.changed_at}-${item.description}`} className="border-t border-border"><Cell>{item.policy_type_label}</Cell><Cell>{item.changed_at}</Cell><Cell>{item.description}</Cell></tr>)}</tbody></Table>}
      </section>
      <section className="flex flex-col gap-3">
        <SectionHeading title="通路營收登記" onAdd={() => setPanel({ kind: "channel-entry" })} />
        {channelEntries.length === 0 ? <p className="text-sm text-muted-foreground">還沒有手動登記的通路營收。</p> : <Table><thead className="bg-muted text-muted-foreground"><tr><Header>通路</Header><Header>日期</Header><Header>金額</Header><Header>數量</Header><Header>備註</Header></tr></thead><tbody>{channelEntries.map((item) => <tr key={`${item.channel}-${item.entry_date}-${item.note}`} className="border-t border-border"><Cell>{item.channel_label}</Cell><Cell>{item.entry_date}</Cell><Cell>{item.revenue === null ? "未填" : formatCurrency(item.revenue)}</Cell><Cell>{item.quantity === null ? "—" : displayNumber(item.quantity)}</Cell><Cell>{item.note || "—"}</Cell></tr>)}</tbody></Table>}
      </section>
    </>;
  }

  return <div className="flex flex-col gap-5">{content}
    {panel?.kind === "import" && <ImportPanel brandId={brandId} onClose={() => setPanel(null)} onSaved={refreshAfterSave} />}
    {panel?.kind === "sku-cost" && <SkuCostPanel brandId={brandId} sku={panel.sku} onClose={() => setPanel(null)} onSaved={refreshAfterSave} />}
    {panel?.kind === "policy-change" && <PolicyChangePanel brandId={brandId} onClose={() => setPanel(null)} onSaved={refreshAfterSave} />}
    {panel?.kind === "channel-entry" && <ChannelEntryPanel brandId={brandId} onClose={() => setPanel(null)} onSaved={refreshAfterSave} />}
  </div>;
}

type PanelProps = { brandId: string; onClose: () => void; onSaved: (message: string) => void };

function ImportPanel({ brandId, onClose, onSaved }: PanelProps) {
  const [file, setFile] = useState<File | null>(null);
  const form = useFormSubmit(async () => { if (!file) throw new Error("請先選擇檔案。"); onSaved(await importOrdersFile(brandId, file)); });
  return <PanelShell title="匯入訂單檔" onClose={onClose}><form className="flex flex-col gap-4" onSubmit={(event) => { event.preventDefault(); void form.submit(); }}><label className="flex flex-col gap-1 text-sm"><span className="font-medium text-foreground">檔案</span><span className="w-fit cursor-pointer rounded-md border border-border bg-card px-4 py-2 font-medium text-foreground hover:bg-muted">選擇檔案</span><input type="file" accept=".xlsx,.xlsm,.csv,text/csv" onChange={(event) => setFile(event.target.files?.[0] ?? null)} className="sr-only" /></label><div onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); setFile(event.dataTransfer.files[0] ?? null); }} className="rounded-md border border-dashed border-border p-5 text-center text-sm text-muted-foreground">{file ? `已選擇：${file.name}` : "把檔案拖到這裡"}<p className="mt-2">EasyStore 訂單匯出（.xlsx）、蝦皮報表、Meta 廣告 CSV 都丟這裡，系統自動認格式。</p></div><FormError message={form.error} /><SubmitButton saving={form.saving} label="開始匯入" pendingLabel="匯入中…" /></form></PanelShell>;
}

function SkuCostPanel({ brandId, sku, onClose, onSaved }: PanelProps & { sku: string }) {
  const [unitCost, setUnitCost] = useState("");
  const form = useFormSubmit(async () => onSaved(await saveSkuCost(brandId, sku, unitCost)));
  return <PanelShell title="登記單位成本" onClose={onClose}><form className="flex flex-col gap-4" onSubmit={(event) => { event.preventDefault(); void form.submit(); }}><p className="text-sm text-muted-foreground">SKU：{sku}</p><label className="flex flex-col gap-1 text-sm"><span className="font-medium text-foreground">單位成本</span><input autoFocus inputMode="decimal" value={unitCost} onChange={(event) => setUnitCost(event.target.value)} className="rounded-md border border-border px-3 py-2 text-sm text-foreground" /></label><FormError message={form.error} /><SubmitButton saving={form.saving} label="儲存成本" pendingLabel="儲存中…" /></form></PanelShell>;
}

function PolicyChangePanel({ brandId, onClose, onSaved }: PanelProps) {
  const [policyType, setPolicyType] = useState("discount");
  const [changedAt, setChangedAt] = useState("");
  const [description, setDescription] = useState("");
  const form = useFormSubmit(async () => onSaved(await createPolicyChange(brandId, { policy_type: policyType, changed_at: changedAt, description })));
  return <PanelShell title="新增口徑變更" onClose={onClose}><form className="flex flex-col gap-4" onSubmit={(event) => { event.preventDefault(); void form.submit(); }}><label className="flex flex-col gap-1 text-sm"><span className="font-medium text-foreground">類型</span><select value={policyType} onChange={(event) => setPolicyType(event.target.value)} className="rounded-md border border-border px-3 py-2 text-sm text-foreground"><option value="discount">折扣規則</option><option value="refund">退款政策</option></select></label><label className="flex flex-col gap-1 text-sm"><span className="font-medium text-foreground">變更日</span><input type="date" value={changedAt} onChange={(event) => setChangedAt(event.target.value)} className="rounded-md border border-border px-3 py-2 text-sm text-foreground" /></label><label className="flex flex-col gap-1 text-sm"><span className="font-medium text-foreground">說明</span><input value={description} onChange={(event) => setDescription(event.target.value)} className="rounded-md border border-border px-3 py-2 text-sm text-foreground" /></label><FormError message={form.error} /><SubmitButton saving={form.saving} label="記錄口徑變更" pendingLabel="儲存中…" /></form></PanelShell>;
}

function ChannelEntryPanel({ brandId, onClose, onSaved }: PanelProps) {
  const [channel, setChannel] = useState("physical_store");
  const [entryDate, setEntryDate] = useState("");
  const [revenue, setRevenue] = useState("");
  const [quantity, setQuantity] = useState("");
  const [note, setNote] = useState("");
  const form = useFormSubmit(async () => onSaved(await createChannelEntry(brandId, { channel, entry_date: entryDate, revenue, quantity, note })));
  return <PanelShell title="新增通路營收" onClose={onClose}><form className="flex flex-col gap-4" onSubmit={(event) => { event.preventDefault(); void form.submit(); }}><label className="flex flex-col gap-1 text-sm"><span className="font-medium text-foreground">通路</span><select value={channel} onChange={(event) => setChannel(event.target.value)} className="rounded-md border border-border px-3 py-2 text-sm text-foreground">{HAND_ENTRY_CHANNEL_TYPES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label className="flex flex-col gap-1 text-sm"><span className="font-medium text-foreground">日期</span><input type="date" value={entryDate} onChange={(event) => setEntryDate(event.target.value)} className="rounded-md border border-border px-3 py-2 text-sm text-foreground" /></label><label className="flex flex-col gap-1 text-sm"><span className="font-medium text-foreground">金額（選填）</span><input inputMode="decimal" value={revenue} onChange={(event) => setRevenue(event.target.value)} className="rounded-md border border-border px-3 py-2 text-sm text-foreground" /></label><label className="flex flex-col gap-1 text-sm"><span className="font-medium text-foreground">數量（選填）</span><input inputMode="decimal" value={quantity} onChange={(event) => setQuantity(event.target.value)} className="rounded-md border border-border px-3 py-2 text-sm text-foreground" /></label><label className="flex flex-col gap-1 text-sm"><span className="font-medium text-foreground">備註（選填）</span><input value={note} onChange={(event) => setNote(event.target.value)} className="rounded-md border border-border px-3 py-2 text-sm text-foreground" /></label><FormError message={form.error} /><SubmitButton saving={form.saving} label="記下這筆" pendingLabel="儲存中…" /></form></PanelShell>;
}

function AttributionButton({ brandId, orderId, excluded, onSaved }: { brandId: string; orderId: string; excluded: boolean; onSaved: (message: string) => void }) {
  const form = useFormSubmit(async () => onSaved(await setOrderAttribution(brandId, orderId, !excluded)));
  return <button type="button" disabled={form.saving} onClick={() => void form.submit()} className="text-left text-sm text-primary hover:underline disabled:opacity-60">{form.saving ? "儲存中…" : excluded ? "已標記非廣告來源，取消" : "標記非廣告來源"}{form.error && <span className="block text-danger">{form.error}</span>}</button>;
}

function PanelShell({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return <SidePanel ariaLabel={title} onClose={onClose}><div className="flex items-start justify-between gap-3 border-b border-border pb-4"><h2 className="font-display text-lg text-foreground">{title}</h2><button type="button" onClick={onClose} aria-label="關閉側板" className="rounded-md p-2 text-muted-foreground hover:bg-muted"><X className="h-4 w-4" aria-hidden="true" /></button></div>{children}</SidePanel>;
}

function SubmitButton({ saving, label, pendingLabel }: { saving: boolean; label: string; pendingLabel: string }) {
  return <button type="submit" disabled={saving} className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60">{saving ? pendingLabel : label}</button>;
}

function FormError({ message }: { message: string | null }) {
  return message ? <p className="text-sm text-danger">{message}</p> : null;
}

function SectionHeading({ title, onAdd }: { title: string; onAdd: () => void }) {
  return <div className="flex items-center justify-between gap-3"><h2 className="font-display text-xl text-foreground">{title}</h2><TextButton onClick={onAdd}>新增</TextButton></div>;
}

function TextButton({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return <button type="button" onClick={onClick} className="text-sm font-medium text-primary hover:underline">{children}</button>;
}

function Table({ children }: { children: ReactNode }) {
  return <div className="overflow-x-auto rounded-md border border-border"><table className="w-full text-left text-sm">{children}</table></div>;
}

function Header({ children }: { children: ReactNode }) {
  return <th className="whitespace-nowrap px-3 py-2 font-medium">{children}</th>;
}

function Cell({ children }: { children: ReactNode }) {
  return <td className="whitespace-nowrap px-3 py-2 text-foreground">{children}</td>;
}
