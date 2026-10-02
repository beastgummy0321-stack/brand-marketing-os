import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { ArrowRight, Upload, X } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { PageTabs } from "@/components/layout/PageTabs";
import { EmptyState } from "@/components/layout/EmptyState";
import { Pager } from "@/components/layout/Pager";
import { SidePanel } from "@/components/layout/SidePanel";
import { Skeleton } from "@/components/layout/Skeleton";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import { Textarea } from "@/components/layout/ui/textarea";
import { Badge } from "@/components/layout/ui/badge";
import { formatCurrency } from "@/lib/format";
import {
  createChannelEntry, createPolicyChange, fetchOrders, HAND_ENTRY_CHANNEL_TYPES,
  importOrdersFile, saveSkuCost, type OrdersPageData, type SkuMargin,
} from "@/lib/ordersApi";
import { useFormSubmit } from "@/lib/useFormSubmit";
import { usePagination } from "@/lib/usePagination";

/** Every format `app/orders/dispatch.import_dropped_file` accepts; one string so the empty
 * states and the import panel cannot drift apart (the Meta ads CSV path was removed there). */
const IMPORT_FORMATS = "EasyStore 訂單匯出（.xlsx）或蝦皮賣家中心報表（.csv）";

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

const tabs = [
  { value: "overview", label: "概況" },
  { value: "orders", label: "訂單" },
  { value: "margins", label: "商品毛利" },
  { value: "channels", label: "通路營收" },
  { value: "policies", label: "口徑紀錄" },
] as const;
type OrdersTab = (typeof tabs)[number]["value"];

function displayNumber(value: number | null): string {
  return value === null ? "累積中" : value.toLocaleString("zh-TW");
}
function displayPercent(value: number | null): string {
  return value === null ? "累積中" : `${Math.round(value * 100)}%`;
}
function displayMargin(value: SkuMargin["margin"]): string {
  return value === null ? "未登記成本" : formatCurrency(value);
}

/** 同一份資料按工作拆分；寫入表單在分頁外掛載，切換分頁不會清除草稿。 */
export function OrdersPage({ brandId }: { brandId: string }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [panel, setPanel] = useState<Panel>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [params, setParams] = useSearchParams();
  const tab = tabs.find((item) => item.value === params.get("tab"))?.value ?? "overview";
  const requestId = useRef(0);
  const data = state.status === "ready" ? state.data : null;
  const marginPage = usePagination(data?.summary.sku_margins ?? []);
  const channelPage = usePagination(data?.channel_entries ?? []);
  const policyPage = usePagination(data?.policy_changes ?? []);

  function changeTab(value: OrdersTab) {
    setParams((previous) => { const next = new URLSearchParams(previous); next.set("tab", value); return next; });
  }

  const load = useCallback((page = 1) => {
    const id = ++requestId.current;
    setState({ status: "loading" });
    fetchOrders(brandId, page)
      .then((next) => { if (id === requestId.current) setState({ status: "ready", data: next }); })
      .catch((err: unknown) => { if (id === requestId.current) setState({ status: "error", message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。" }); });
  }, [brandId]);
  function refreshAfterSave(message: string) {
    const page = data?.orders.page ?? 1;
    setPanel(null);
    setSuccessMessage(message);
    load(page);
  }
  useEffect(() => {
    setPanel(null);
    setSuccessMessage(null);
    load();
    return () => { requestId.current += 1; };
  }, [brandId, load]);

  let content: ReactNode;
  if (state.status === "loading") {
    content = <div aria-label="訂單資料載入中" className="flex flex-col gap-4"><div className="grid grid-cols-5 gap-4">{Array.from({ length: 5 }, (_, index) => <Skeleton key={index} className="h-28" />)}</div><Skeleton className="h-80" /></div>;
  } else if (state.status === "error") {
    content = <div className="surface"><EmptyState title="讀取失敗" description={state.message} onAction={() => load()} actionLabel="重新載入" /></div>;
  } else {
    const { summary, orders, policy_changes: policyChanges, channel_entries: channelEntries } = state.data;
    const noData = !summary.has_history && orders.total === 0;
    const missingCosts = summary.sku_margins.filter((item) => item.unit_cost === null).length;
    const customerCount = summary.new_customers + summary.existing_customers;
    content = <>
      {tab === "overview" && (noData ? <div className="surface"><EmptyState title="還沒有訂單資料" description={`匯入${IMPORT_FORMATS}後，即可查看實收營收、訂單與顧客統計。`} actionLabel="匯入訂單檔" onAction={() => setPanel({ kind: "import" })} /></div> : <>
        <div className="grid grid-cols-5 gap-3">
          <Metric label="實收營收" value={formatCurrency(summary.net_revenue)} />
          <Metric label="訂單數" value={displayNumber(summary.order_count)} />
          <Metric label="平均客單價" value={formatCurrency(summary.average_order_value)} />
          <Metric label="新客／舊客" value={`${summary.new_customers}／${summary.existing_customers}`} />
          <Metric label="回購率" value={displayPercent(summary.repurchase_rate)} />
        </div>
        <div className="grid grid-cols-2 gap-5">
          <section className="surface">
            <div className="surface-header"><h2>顧客組成</h2><span className="text-xs text-muted-foreground">最近 30 天</span></div>
            <div className="surface-body flex flex-col gap-5">
              <div className="grid grid-cols-2 gap-5">
                <div><p className="text-sm text-muted-foreground">新客</p><p className="mt-2 text-2xl font-semibold numeric">{displayNumber(summary.new_customers)}</p></div>
                <div><p className="text-sm text-muted-foreground">舊客</p><p className="mt-2 text-2xl font-semibold numeric">{displayNumber(summary.existing_customers)}</p></div>
              </div>
              {customerCount > 0 && <div aria-label={`顧客組成：新客 ${summary.new_customers}，舊客 ${summary.existing_customers}`} className="flex h-2.5 overflow-hidden rounded-full bg-muted"><span className="bg-primary" style={{ width: `${summary.new_customers / customerCount * 100}%` }} /><span className="flex-1 bg-chart-aqua" /></div>}
              <p className="text-xs leading-6 text-muted-foreground">回購率依既有訂單紀錄計算，樣本數 {displayNumber(summary.repurchase_sample_size)}。資料不足時顯示「累積中」。</p>
            </div>
          </section>
          <section className="surface">
            <div className="surface-header"><h2>毛利資料準備</h2><Badge variant={missingCosts > 0 ? "outline" : "secondary"}>{missingCosts > 0 ? "待補成本" : summary.sku_margins.length > 0 ? "已登記成本" : "尚無商品資料"}</Badge></div>
            <div className="surface-body flex flex-col gap-4">
              <p className="text-2xl font-semibold numeric">{missingCosts}<span className="ml-2 text-sm font-normal text-muted-foreground">項商品未登記成本</span></p>
              <p className="text-sm leading-6 text-muted-foreground">逐項商品毛利依這段期間的訂單與單位成本計算。未登記成本的商品不會顯示為零毛利。</p>
              <Button type="button" variant="outline" className="self-start" onClick={() => changeTab("margins")}>查看商品毛利<ArrowRight className="size-4" aria-hidden="true" /></Button>
            </div>
          </section>
        </div>
        <div className="surface flex items-center justify-between gap-5 px-5 py-4">
          <p className="max-w-[var(--width-prose)] text-sm leading-6 text-muted-foreground">官網訂單與手動登記的其他通路營收分開呈現；其他通路不會加進這裡的訂單統計。</p>
          <Button type="button" variant="ghost" onClick={() => changeTab("channels")}>查看通路營收<ArrowRight className="size-4" aria-hidden="true" /></Button>
        </div>
      </>)}
      {tab === "orders" && <section className="surface">
        <div className="surface-header"><h2>最近訂單</h2><span className="text-xs text-muted-foreground">共 {orders.total} 筆</span></div>
        <div className="surface-body">
          {orders.items.length === 0 ? <EmptyState title="目前沒有訂單" description={`匯入${IMPORT_FORMATS}後，即可在這裡查看訂單明細。`} actionLabel="匯入訂單檔" onAction={() => setPanel({ kind: "import" })} /> : <>
            <Table><thead><tr><Header>訂單編號</Header><Header>日期</Header><Header>金額</Header><Header>訂單狀態</Header><Header>優惠碼</Header></tr></thead><tbody>{orders.items.map((item) => <tr key={item.id} className="border-t border-border"><Cell>{item.order_number}</Cell><Cell>{item.order_date ?? "—"}</Cell><Cell>{formatCurrency(item.total_amount)}</Cell><Cell><Badge variant="outline">{item.order_status ?? "—"}</Badge></Cell><Cell>{item.voucher_code ?? "—"}</Cell></tr>)}</tbody></Table>
            <div className="mt-4"><Pager page={orders.page} pageCount={Math.ceil(orders.total / orders.page_size)} totalCount={orders.total} onChange={load} /></div>
          </>}
        </div>
      </section>}
      {tab === "margins" && <section className="surface">
        <div className="surface-header"><h2>逐項商品毛利</h2><span className="text-xs text-muted-foreground">{missingCosts > 0 ? `${missingCosts} 項待補成本` : `${summary.sku_margins.length} 項商品`}</span></div>
        <div ref={marginPage.topRef} className="surface-body flex flex-col gap-4">
          <p className="text-sm text-muted-foreground">營收依訂單統計；登記單位成本後，才會計算該商品的毛利。</p>
          {summary.sku_margins.length === 0 ? <EmptyState title="還沒有可統計的商品" description="這段期間沒有 SKU 訂單資料，匯入後再回來查看。" /> : <>
            <Table><thead><tr><Header>SKU</Header><Header>數量</Header><Header>營收</Header><Header>單位成本</Header><Header>毛利</Header><Header>動作</Header></tr></thead><tbody>{marginPage.pageItems.map((item) => <tr key={item.sku} className="border-t border-border"><Cell>{item.sku}</Cell><Cell>{displayNumber(item.quantity)}</Cell><Cell>{formatCurrency(item.revenue)}</Cell><Cell>{item.unit_cost === null ? <span className="text-warning">未登記成本</span> : formatCurrency(item.unit_cost)}</Cell><Cell>{displayMargin(item.margin)}</Cell><Cell><TextButton onClick={() => setPanel({ kind: "sku-cost", sku: item.sku })}>登記成本</TextButton></Cell></tr>)}</tbody></Table>
            <Pager page={marginPage.page} pageCount={marginPage.pageCount} totalCount={marginPage.totalCount} onChange={marginPage.goToPage} />
          </>}
        </div>
      </section>}
      {tab === "channels" && <section className="surface">
        <div className="surface-header"><SectionHeading title="通路營收登記" onAdd={() => setPanel({ kind: "channel-entry" })} /></div>
        <div ref={channelPage.topRef} className="surface-body flex flex-col gap-4">
          <p className="text-sm text-muted-foreground">登記官網以外的通路。官網營收由訂單匯入記帳，不需要再填一次。</p>
          {channelEntries.length === 0 ? <EmptyState title="還沒有通路營收紀錄" description="可登記實體店、平台商店或其他通路的營收。" actionLabel="新增通路營收" onAction={() => setPanel({ kind: "channel-entry" })} /> : <>
            <Table><thead><tr><Header>通路</Header><Header>日期</Header><Header>金額</Header><Header>數量</Header><Header>備註</Header></tr></thead><tbody>{channelPage.pageItems.map((item, index) => <tr key={`${item.channel}-${item.entry_date}-${index}`} className="border-t border-border"><Cell>{item.channel_label}</Cell><Cell>{item.entry_date}</Cell><Cell>{item.revenue === null ? "未填" : formatCurrency(item.revenue)}</Cell><Cell>{item.quantity === null ? "—" : displayNumber(item.quantity)}</Cell><Cell wrap>{item.note || "—"}</Cell></tr>)}</tbody></Table>
            <Pager page={channelPage.page} pageCount={channelPage.pageCount} totalCount={channelPage.totalCount} onChange={channelPage.goToPage} />
          </>}
        </div>
      </section>}
      {tab === "policies" && <section className="surface">
        <div className="surface-header"><SectionHeading title="口徑變更紀錄" onAdd={() => setPanel({ kind: "policy-change" })} /></div>
        <div ref={policyPage.topRef} className="surface-body flex flex-col gap-4">
          <p className="text-sm text-muted-foreground">記下折扣規則與退款政策的變更，讓前後數據有脈絡可查。</p>
          {policyChanges.length === 0 ? <EmptyState title="還沒有口徑變更紀錄" description="規則改變時，記錄日期與說明，方便之後回看。" actionLabel="新增口徑變更" onAction={() => setPanel({ kind: "policy-change" })} /> : <>
            <Table><thead><tr><Header>類型</Header><Header>變更日</Header><Header>說明</Header></tr></thead><tbody>{policyPage.pageItems.map((item, index) => <tr key={`${item.policy_type}-${item.changed_at}-${index}`} className="border-t border-border"><Cell>{item.policy_type_label}</Cell><Cell>{item.changed_at}</Cell><Cell wrap>{item.description}</Cell></tr>)}</tbody></Table>
            <Pager page={policyPage.page} pageCount={policyPage.pageCount} totalCount={policyPage.totalCount} onChange={policyPage.goToPage} />
          </>}
        </div>
      </section>}
    </>;
  }

  return <div className="flex flex-col gap-5">
    <PageHeader title="訂單與顧客" description={data ? `${data.brand.name} · 統計區間 ${data.summary.since} ～ ${data.summary.until}（最近 30 天）` : "查看訂單、顧客與商品毛利。"} actions={<Button type="button" onClick={() => setPanel({ kind: "import" })}><Upload className="size-4" aria-hidden="true" />匯入訂單檔</Button>} />
    <PageTabs items={[...tabs]} value={tab} onChange={changeTab} />
    {successMessage && <p role="status" className="rounded-lg border border-success/25 bg-success/5 px-4 py-3 text-sm text-foreground">{successMessage}</p>}
    {content}
    {panel?.kind === "import" && <ImportPanel brandId={brandId} onClose={() => setPanel(null)} onSaved={refreshAfterSave} />}
    {panel?.kind === "sku-cost" && <SkuCostPanel brandId={brandId} sku={panel.sku} onClose={() => setPanel(null)} onSaved={refreshAfterSave} />}
    {panel?.kind === "policy-change" && <PolicyChangePanel brandId={brandId} onClose={() => setPanel(null)} onSaved={refreshAfterSave} />}
    {panel?.kind === "channel-entry" && <ChannelEntryPanel brandId={brandId} onClose={() => setPanel(null)} onSaved={refreshAfterSave} />}
  </div>;
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="surface px-4 py-5"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-3 text-[clamp(20px,1.7vw,30px)] font-semibold tracking-tight numeric">{value}</p></div>;
}
type PanelProps = { brandId: string; onClose: () => void; onSaved: (message: string) => void };

function ImportPanel({ brandId, onClose, onSaved }: PanelProps) {
  const [file, setFile] = useState<File | null>(null);
  const form = useFormSubmit(async () => { if (!file) throw new Error("請先選擇檔案。"); onSaved(await importOrdersFile(brandId, file)); });
  return <PanelShell title="匯入訂單檔" onClose={onClose}><form className="flex flex-col gap-4" {...form.formProps} onSubmit={(event) => { event.preventDefault(); void form.submit(); }}><label className="flex flex-col gap-1 text-sm"><span className="font-medium text-foreground">檔案</span><span className="w-fit cursor-pointer rounded-md border border-border bg-card px-4 py-2 font-medium text-foreground hover:bg-muted">選擇檔案</span><Input type="file" accept=".xlsx,.xlsm,.csv,text/csv" onChange={(event) => setFile(event.target.files?.[0] ?? null)} className="sr-only" /></label><div onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); setFile(event.dataTransfer.files[0] ?? null); }} className="rounded-md border border-dashed border-border p-5 text-center text-sm text-muted-foreground">{file ? `已選擇：${file.name}` : "把檔案拖到這裡"}<p className="mt-2">{IMPORT_FORMATS}都丟這裡，系統自動認格式。</p></div><FormError message={form.error} /><SubmitButton saving={form.saving} label="開始匯入" pendingLabel="匯入中…" /></form></PanelShell>;
}

function SkuCostPanel({ brandId, sku, onClose, onSaved }: PanelProps & { sku: string }) {
  const [unitCost, setUnitCost] = useState("");
  const form = useFormSubmit(async () => onSaved(await saveSkuCost(brandId, sku, unitCost)));
  return <PanelShell title="登記單位成本" onClose={onClose}><form className="flex flex-col gap-4" {...form.formProps} onSubmit={(event) => { event.preventDefault(); void form.submit(); }}><p className="text-sm text-muted-foreground">SKU：{sku}</p><label className="flex flex-col gap-1 text-sm"><span className="font-medium text-foreground">單位成本</span><Input autoFocus inputMode="decimal" value={unitCost} onChange={(event) => setUnitCost(event.target.value)} className="rounded-md border border-border px-3 py-2 text-sm text-foreground" /></label><FormError message={form.error} /><SubmitButton saving={form.saving} label="儲存成本" pendingLabel="儲存中…" /></form></PanelShell>;
}

function PolicyChangePanel({ brandId, onClose, onSaved }: PanelProps) {
  const [policyType, setPolicyType] = useState("discount");
  const [changedAt, setChangedAt] = useState("");
  const [description, setDescription] = useState("");
  const form = useFormSubmit(async () => onSaved(await createPolicyChange(brandId, { policy_type: policyType, changed_at: changedAt, description })));
  return <PanelShell title="新增口徑變更" onClose={onClose}><form className="flex flex-col gap-4" {...form.formProps} onSubmit={(event) => { event.preventDefault(); void form.submit(); }}><label className="flex flex-col gap-1 text-sm"><span className="font-medium text-foreground">類型</span><select value={policyType} onChange={(event) => setPolicyType(event.target.value)} className="rounded-md border border-border px-3 py-2 text-sm text-foreground"><option value="discount">折扣規則</option><option value="refund">退款政策</option></select></label><label className="flex flex-col gap-1 text-sm"><span className="font-medium text-foreground">變更日</span><Input type="date" value={changedAt} onChange={(event) => setChangedAt(event.target.value)} className="rounded-md border border-border px-3 py-2 text-sm text-foreground" /></label><label className="flex flex-col gap-1 text-sm"><span className="font-medium text-foreground">說明</span><Textarea rows={4} value={description} onChange={(event) => setDescription(event.target.value)} className="rounded-md border border-border px-3 py-2 text-sm text-foreground" /></label><FormError message={form.error} /><SubmitButton saving={form.saving} label="記錄口徑變更" pendingLabel="儲存中…" /></form></PanelShell>;
}

function ChannelEntryPanel({ brandId, onClose, onSaved }: PanelProps) {
  const [channel, setChannel] = useState("physical_store");
  const [entryDate, setEntryDate] = useState("");
  const [revenue, setRevenue] = useState("");
  const [quantity, setQuantity] = useState("");
  const [note, setNote] = useState("");
  // F47-I03 (drill-10 甲 訂單 #5): the amount is sent as typed (the server keeps 0 as 0 and refuses a
  // negative with 「營收不能是負數。」); a sentence about the amount or the quantity shows under that
  // field, any other one at the end of the form, and it clears once a field changes.
  const form = useFormSubmit(async () => onSaved(await createChannelEntry(brandId, { channel, entry_date: entryDate, revenue, quantity, note })));
  const errorField = form.error?.startsWith("營收") ? "revenue" : form.error?.startsWith("數量") ? "quantity" : null;
  return <PanelShell title="新增通路營收" onClose={onClose}><form className="flex flex-col gap-4" {...form.formProps} onSubmit={(event) => { event.preventDefault(); void form.submit(); }}><label className="flex flex-col gap-1 text-sm"><span className="font-medium text-foreground">通路</span><select value={channel} onChange={(event) => setChannel(event.target.value)} className="rounded-md border border-border px-3 py-2 text-sm text-foreground">{HAND_ENTRY_CHANNEL_TYPES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label className="flex flex-col gap-1 text-sm"><span className="font-medium text-foreground">日期</span><Input type="date" value={entryDate} onChange={(event) => setEntryDate(event.target.value)} className="rounded-md border border-border px-3 py-2 text-sm text-foreground" /></label><label className="flex flex-col gap-1 text-sm"><span className="font-medium text-foreground">金額（選填）</span><Input inputMode="decimal" value={revenue} onChange={(event) => setRevenue(event.target.value)} aria-invalid={errorField === "revenue" ? true : undefined} className="rounded-md border border-border px-3 py-2 text-sm text-foreground" />{errorField === "revenue" && <FormError message={form.error} />}</label><label className="flex flex-col gap-1 text-sm"><span className="font-medium text-foreground">數量（選填）</span><Input inputMode="decimal" value={quantity} onChange={(event) => setQuantity(event.target.value)} aria-invalid={errorField === "quantity" ? true : undefined} className="rounded-md border border-border px-3 py-2 text-sm text-foreground" />{errorField === "quantity" && <FormError message={form.error} />}</label><label className="flex flex-col gap-1 text-sm"><span className="font-medium text-foreground">備註（選填）</span><Textarea rows={3} value={note} onChange={(event) => setNote(event.target.value)} className="rounded-md border border-border px-3 py-2 text-sm text-foreground" /></label>{errorField === null && <FormError message={form.error} />}<SubmitButton saving={form.saving} label="記下這筆" pendingLabel="儲存中…" /></form></PanelShell>;
}

function PanelShell({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return <SidePanel ariaLabel={title} onClose={onClose}><div className="flex items-start justify-between gap-3 border-b border-border pb-4"><h2 className="font-display text-lg text-foreground">{title}</h2><button type="button" onClick={onClose} aria-label="關閉側板" className="rounded-md p-2 text-muted-foreground hover:bg-muted"><X className="h-4 w-4" aria-hidden="true" /></button></div>{children}</SidePanel>;
}

function SubmitButton({ saving, label, pendingLabel }: { saving: boolean; label: string; pendingLabel: string }) {
  return <Button type="submit" disabled={saving}>{saving ? pendingLabel : label}</Button>;
}

function FormError({ message }: { message: string | null }) {
  return message ? <p role="alert" className="text-sm text-danger">{message}</p> : null;
}

function SectionHeading({ title, onAdd }: { title: string; onAdd: () => void }) {
  return <div className="flex w-full items-center justify-between gap-3"><h2>{title}</h2><Button type="button" variant="outline" size="sm" onClick={onAdd}>新增</Button></div>;
}

function TextButton({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return <Button type="button" variant="ghost" size="sm" onClick={onClick} className="text-primary">{children}</Button>;
}

function Table({ children }: { children: ReactNode }) {
  return <div className="table-surface"><table className="w-full text-left text-sm">{children}</table></div>;
}

function Header({ children }: { children: ReactNode }) {
  return <th className="whitespace-nowrap px-4 py-3 font-medium">{children}</th>;
}

function Cell({ children, wrap = false }: { children: ReactNode; wrap?: boolean }) {
  return <td className={`px-4 py-3 text-foreground ${wrap ? "min-w-48 whitespace-normal break-words" : "whitespace-nowrap"}`}>{children}</td>;
}


