import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import type { AssumptionField, ProductSellWays, SellWayInput, SellWayRow } from "@/lib/intakeProductApi";
import { completeProductOnboarding, fetchProductSellWays, saveProductSellWays } from "@/lib/intakeProductApi";
import { BarNext, OnboardingBar, OnboardingStepHead, type BarBack, type StepNav } from "../OnboardingStepHead";
import { contentsError, qtyOf, SellWayContents, type ContentItem } from "./SellWayContents";
import { SellWayEditor, SellWaySummary } from "./SellWayEditor";
import { draftFromMoney, emptyDraft, moneyErrors, PriceBlock, stepMoneyInput, type MoneyDraft } from "./SellWayTable";

interface Row {
  key: string;
  id: string | null;
  name: string;
  shape: "base" | "composed";
  /** Composed only: base rows (by key) × qty. */
  items: ContentItem[];
  draft: MoneyDraft;
  free: boolean;
  /** The server's row after the last save; null = not saved yet (nothing derived). */
  server: SellWayRow | null;
}

const errorText = (err: unknown) => (err instanceof Error ? err.message : "儲存失敗，請稍後再試。");
const fold = (s: string) => s.trim().toLowerCase();

/** Product onboarding step 4 怎麼賣、賣多少 (F45; prototype `.harness/scratch/prototype/f45-sell-way-components`):
 * 基本賣法 (one product, no quantity: the unit) and 組合賣法 (base sell-ways × qty), one summary row each; one row at a
 * time opens inline as the editor (`SellWayEditor`: 名稱, 商品 or 裡面有什麼, the shared `PriceBlock`). 「＋基本賣法」
 * 「＋組合賣法（例如 6 盒）」, the pointer to the bundle page and the reference-value fold sit under the list.
 *
 * Every save sends the whole list through `PUT …/onboarding/sell-ways` (raw inputs; composed rows name their bases;
 * no `qty`): when focus leaves an editor field, on 「完成」, on a contents / 免運 change and on delete. The page then
 * shows the server's numbers (derived 售價 / 原價 / 成本 labelled 推算, 打平, offer sentences, the bases a cost waits
 * for); nothing is computed here. A refused save shows the server's text as is. 完成商品建檔 saves what is left, then
 * `POST …/onboarding/complete`, and moves on only after both succeeded. */
export function SellWaysStep({ brandId, productId, nav, back, onNext }: {
  brandId: string;
  productId: string;
  nav: StepNav;
  back: BarBack;
  onNext: () => void;
}) {
  const [data, setData] = useState<ProductSellWays | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  /** The composed row to return to after filling a base's cost. */
  const [ret, setRet] = useState<string | null>(null);
  const [picking, setPicking] = useState<string | null>(null);
  const [tried, setTried] = useState<Set<string>>(new Set());
  const [focus, setFocus] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const uid = useRef(0);
  const rowsRef = useRef<Row[]>([]);
  rowsRef.current = rows;
  /** The last list the server confirmed (without ids): an unchanged list is not sent again. */
  const savedSig = useRef<string | null>(null);
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const alive = useRef(true);
  const show = data?.show_close_rate ?? false;

  useEffect(() => {
    alive.current = true;
    fetchProductSellWays(brandId, productId)
      .then((loaded) => {
        if (!alive.current) return;
        setData(loaded);
        const list = fromServer(loaded.sell_ways);
        setRows(list);
        if (list.length > 0 && list.every((r) => r.id)) savedSig.current = sig(list, loaded.show_close_rate);
        if (list.length === 0) addRow("base", list);
      })
      .catch((err: unknown) => alive.current && setLoadError(err instanceof Error ? err.message : "讀取失敗，請稍後再試。"));
    return () => {
      alive.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brandId, productId]);

  useEffect(() => {
    if (!focus) return;
    const el = document.getElementById(focus);
    if (el) {
      el.focus();
      el.scrollIntoView?.({ block: "center" });
    }
    setFocus(null);
  }, [focus]);

  /** Server rows -> page rows; a composed row's components point at base rows (by id, or by name on a proposal). */
  function fromServer(list: SellWayRow[]): Row[] {
    const out: Row[] = list.map((w) => ({
      key: `sw${uid.current++}`, id: w.id, name: w.name, shape: w.shape, items: [], draft: draftFromMoney(w),
      free: w.free_shipping, server: w.id ? w : null,
    }));
    list.forEach((w, i) => {
      out[i].items = w.components.flatMap((c) => {
        const base = out.find((r, j) => r.shape === "base" && (c.sell_way_id ? r.id === c.sell_way_id : fold(list[j].name) === fold(c.name)));
        return base ? [{ base: base.key, qty: String(c.qty) }] : [];
      });
    });
    return out;
  }

  const sig = (list: Row[], closeRate: boolean) => JSON.stringify(toInput(list, closeRate).map(({ id: _id, ...rest }) => rest));

  function toInput(list: Row[], closeRate: boolean): SellWayInput[] {
    const names = new Map(list.map((r) => [r.key, r.name.trim()]));
    return list.map((r) => ({
      id: r.id,
      name: r.name.trim(),
      ...stepMoneyInput(r.draft, closeRate),
      free_shipping: r.free,
      ...(r.shape === "composed" ? { components: r.items.map((it) => ({ base: names.get(it.base) ?? "", qty: qtyOf(it.qty) ?? 0 })) } : {}),
    }));
  }

  function rowValid(row: Row, list: Row[]): boolean {
    if (!row.name.trim() || Object.keys(moneyErrors(row.draft, show, row.shape)).length > 0) return false;
    return row.shape === "base" || contentsError(row.items, (k) => list.find((r) => r.key === k)?.name ?? "") === null;
  }

  /** The rows a save sends: every saved row (it must be valid: a row left out is archived) and the new ones that are
   * valid (a new row still being filled in stays on the page unsaved); a composed row goes only with its bases.
   * null = nothing can be saved. */
  function sendable(list: Row[]): Row[] | null {
    if (list.some((r) => r.id !== null && !rowValid(r, list))) return null;
    let out = list.filter((r) => r.id !== null || rowValid(r, list));
    out = out.filter((r) => r.shape === "base" || r.items.every((it) => out.some((b) => b.key === it.base)));
    if (list.some((r) => r.id !== null && !out.includes(r))) return null;
    return out.length > 0 ? out : null;
  }

  /** Saves what can be saved when it changed; resolves the server's list (true = nothing changed), or null. */
  function persist(): Promise<ProductSellWays | null | true> {
    const run = queue.current.then(async (): Promise<ProductSellWays | null | true> => {
      const current = sendable(rowsRef.current);
      if (current === null) return null;
      const signature = sig(current, show);
      if (signature === savedSig.current && current.every((r) => r.id)) return true;
      const sent = current.map((r) => ({ key: r.key, id: r.id, name: fold(r.name) }));
      try {
        const res = await saveProductSellWays(brandId, productId, toInput(current, show));
        savedSig.current = signature;
        const byId = new Map(res.sell_ways.filter((w) => w.id).map((w) => [w.id as string, w]));
        const byName = new Map(res.sell_ways.map((w) => [fold(w.name), w]));
        const serverFor = new Map(sent.map((s) => [s.key, (s.id && byId.get(s.id)) || byName.get(s.name)]));
        if (alive.current) {
          setSaveError(null);
          setRows((prev) => prev.map((r) => {
            const w = serverFor.get(r.key);
            return w ? { ...r, id: w.id, server: w } : r;
          }));
        }
        return res;
      } catch (err) {
        if (alive.current) setSaveError(errorText(err));
        return null;
      }
    });
    queue.current = run.catch(() => undefined);
    return run;
  }

  /** Let the last keystroke settle, then save. */
  const later = () => window.setTimeout(() => void persist(), 0);
  const patchRow = (key: string, patch: Partial<Row>) => setRows((prev) => prev.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const patchItems = (key: string, fn: (items: ContentItem[]) => ContentItem[]) =>
    setRows((prev) => prev.map((r) => (r.key === key ? { ...r, items: fn(r.items) } : r)));
  const markTried = (key: string) => setTried((prev) => new Set(prev).add(key));

  function addRow(shape: "base" | "composed", base: Row[] = rowsRef.current) {
    const key = `sw${uid.current++}`;
    const row: Row = { key, id: null, name: "", shape, items: [], draft: emptyDraft(), free: false, server: null };
    setRows([...dropAbandoned(base), row]);
    setOpen(key);
    setRet(null);
    setPicking(shape === "composed" ? key : null);
    setFocus(`${key}-name`);
  }

  /** A row added on this visit and left blank is dropped when another row opens. */
  function dropAbandoned(list: Row[]): Row[] {
    return list.filter((r) => r.key !== open || r.id !== null || r.server !== null || r.name.trim() || r.items.length || r.draft.price.trim());
  }

  /** Another row may open only when the open one could be saved (a blank new one is dropped instead). */
  function canLeave(): boolean {
    const current = rowsRef.current.find((r) => r.key === open);
    if (!current || rowValid(current, rowsRef.current)) return true;
    if (dropAbandoned([current]).length === 0) return true;
    markTried(current.key);
    setStatus("還有欄位要改，紅字的地方");
    return false;
  }

  function openRow(key: string, field = "name", from: string | null = null) {
    if (key !== open && !canLeave()) return;
    setRows((prev) => dropAbandoned(prev));
    const row = rowsRef.current.find((r) => r.key === key);
    setOpen(key);
    setRet(from);
    setPicking(row?.shape === "composed" && row.items.length === 0 ? key : null);
    setFocus(`${key}-${field}`);
    setStatus(null);
  }

  /** 「完成」 / 「填好了，回到「…」」: save; then close, or reopen the composed row that waited for this cost. */
  async function done(key: string) {
    markTried(key);
    const row = rowsRef.current.find((r) => r.key === key);
    if (!row || !rowValid(row, rowsRef.current)) {
      setStatus("還有欄位要改，紅字的地方");
      return;
    }
    const blocker = rowsRef.current.find((r) => r.key !== key && r.id !== null && !rowValid(r, rowsRef.current));
    if (blocker) {
      markTried(blocker.key);
      setStatus(`「${blocker.name.trim() || "還沒取名的賣法"}」還有欄位要改，改好才能一起存`);
      return;
    }
    if (!sendable(rowsRef.current)?.includes(row)) {
      setStatus("裡面有基本賣法還沒填好，先把它完成");
      return;
    }
    setBusy(true);
    const res = await persist();
    if (alive.current) setBusy(false);
    if (!res || !alive.current) return;
    const back = ret;
    setRet(null);
    setPicking(null);
    if (back) {
      const target = rowsRef.current.find((r) => r.key === back);
      const w = target && res !== true ? res.sell_ways.find((s) => s.id === target.id) : target?.server;
      setOpen(back);
      setFocus(`${back}-name`);
      setStatus(w?.break_even != null
        ? `「${w.name}」的打平算出來了：每筆最多花 NT$${Math.max(w.break_even, 0).toLocaleString("en-US")}`
        : `「${target?.name ?? ""}」還差：${(w?.cost_missing ?? []).map((m) => m.name).join("、")}還沒填成本`);
    } else {
      setOpen(null);
      setStatus(`已儲存「${row.name.trim()}」`);
    }
  }

  async function remove(key: string) {
    const before = rowsRef.current;
    const row = before.find((r) => r.key === key);
    const next = before.filter((r) => r.key !== key).map((r) => ({ ...r, items: r.items.filter((it) => it.base !== key) }));
    rowsRef.current = next;
    setRows(next);
    setOpen(null);
    setRet(null);
    if (!row?.id && !row?.server) {
      setStatus(row?.name.trim() ? `已刪除「${row.name.trim()}」` : "已刪除");
      return;
    }
    setBusy(true);
    const res = await persist();
    if (!alive.current) return;
    setBusy(false);
    if (res) setStatus(`已刪除「${row.name.trim()}」`);
    else {
      setRows(before);
      setOpen(key);
    }
  }

  async function finish() {
    const current = rowsRef.current;
    const invalid = current.filter((r) => !rowValid(r, current));
    if (invalid.length > 0) {
      invalid.forEach((r) => markTried(r.key));
      setOpen(invalid[0].key);
      setStatus("還有欄位要改，紅字的地方");
      return;
    }
    setBusy(true);
    try {
      if (!(await persist())) return;
      await completeProductOnboarding(brandId, productId);
      onNext();
    } catch (err) {
      if (alive.current) setSaveError(errorText(err));
    } finally {
      if (alive.current) setBusy(false);
    }
  }

  /** 「不知道？用同業參考值」 (F05 rule 3): fills the empty field of every row and flags it 假設. A composed row's cost
   * comes from its bases; it is not filled. */
  function fillAssumed(field: AssumptionField) {
    if (!data) return;
    const bm = data.assumptions;
    setRows((prev) => prev.map((r) => {
      if (r.draft[field] !== "") return r;
      let value: string | null = null;
      if (field === "shipping") value = String(bm.shipping_cost.value);
      if (field === "close_rate" && bm.close_rate) value = String(Number((bm.close_rate.value * 100).toFixed(2)));
      if (field === "cost") {
        const price = Number(r.draft.price);
        if (r.shape === "composed" || !(price > 0)) return r;
        value = String(Math.round(price * (1 - bm.gross_margin.value)));
      }
      if (value === null) return r;
      return { ...r, draft: { ...r.draft, [field]: value, assumptions: [...r.draft.assumptions.filter((a) => a !== field), field] } };
    }));
    later();
  }

  const head = <OnboardingStepHead {...nav} title="怎麼賣、賣多少" purpose="先定一份賣多少，再用它湊組合；優惠直接從這裡算" />;

  if (loadError) {
    return (
      <div className="flex flex-col gap-4">
        {head}
        <p role="alert" className="text-sm text-danger">{loadError}</p>
        <OnboardingBar back={back} />
      </div>
    );
  }

  const productName = nav.crumb[nav.crumb.length - 1]?.label ?? "";
  const bases = rows.filter((r) => r.shape === "base");
  const combos = rows.filter((r) => r.shape === "composed");
  const nameOf = (key: string) => rows.find((r) => r.key === key)?.name.trim() || "新的基本賣法";
  const baseOptions = bases.map((b) => ({
    key: b.key,
    name: b.name,
    price: b.server?.price ?? (Number(b.draft.price) > 0 ? Number(b.draft.price) : null),
    cost: b.server?.cost ?? (b.draft.cost.trim() !== "" && Number(b.draft.cost) >= 0 ? Number(b.draft.cost) : null),
  }));
  /** Composed rows (by name) that hold a base: the server's `used_by` plus the ones on the page. */
  const usersOf = (b: Row) => [...new Set([...(b.server?.used_by ?? []), ...combos.filter((c) => c.items.some((it) => it.base === b.key)).map((c) => c.name.trim())])];
  const baseNoCost = (b: Row) => b.draft.cost.trim() === "" && b.server?.cost == null;
  const waiting = bases.find((b) => baseNoCost(b) && combos.some((c) => c.items.some((it) => it.base === b.key)));

  const item = (r: Row) => {
    const showErrors = tried.has(r.key);
    if (open !== r.key) {
      return (
        <SellWaySummary key={r.key} name={r.name} shape={r.shape} numbers={r.server} typedPrice={r.draft.price}
          content={r.shape === "base" ? "一份" : r.items.map((it) => `${nameOf(it.base)} × ${it.qty}`).join(" ＋ ") || "還沒放東西"}
          costMissing={r.shape === "base" && baseNoCost(r)} onEdit={() => openRow(r.key)} />
      );
    }
    const qtyBad = r.shape === "composed" && r.items.some((it) => qtyOf(it.qty) === null);
    const pending = r.shape === "composed" && r.items.length === 0 ? "先填售價或放進賣法" : qtyBad ? "先填數量" : null;
    const retRow = ret ? rows.find((x) => x.key === ret) : undefined;
    return (
      <div key={r.key} onBlur={(e) => {
        if ((e.target as HTMLElement).tagName === "INPUT" && (e.target as HTMLInputElement).type !== "checkbox") later();
      }}>
        <SellWayEditor
          rowKey={r.key}
          shape={r.shape}
          name={r.name}
          productName={productName}
          showErrors={showErrors}
          returnTo={retRow ? retRow.name.trim() : null}
          usedBy={r.shape === "base" ? usersOf(r) : []}
          busy={busy}
          onName={(name) => patchRow(r.key, { name })}
          onDelete={() => void remove(r.key)}
          onDone={() => void done(r.key)}
          contents={r.shape === "composed" && (
            <SellWayContents
              idPrefix={r.key}
              items={r.items}
              bases={baseOptions}
              picking={picking === r.key}
              showErrors={showErrors}
              onQty={(i, qty) => patchItems(r.key, (items) => items.map((it, j) => (j === i ? { ...it, qty } : it)))}
              onRemove={(i) => {
                patchItems(r.key, (items) => items.filter((_, j) => j !== i));
                if (r.items.length === 1) setPicking(r.key);
                later();
              }}
              onAdd={(base) => {
                patchItems(r.key, (items) => [...items, { base, qty: "" }]);
                setPicking(null);
                setFocus(`${r.key}-q${r.items.length}`);
              }}
              onPicking={(on) => setPicking(on ? r.key : null)}
              onNewBase={() => addRow("base")}
            />
          )}
          price={(
            <PriceBlock
              idPrefix={r.key}
              shape={r.shape}
              draft={r.draft}
              numbers={r.server}
              free={r.free}
              showCloseRate={show}
              showErrors={showErrors}
              pending={pending}
              landingPlaceholder={r.server?.landing_is_default ? r.server.landing_url : ""}
              onDraft={(patch) => patchRow(r.key, { draft: { ...r.draft, ...patch } })}
              onFree={(free) => {
                patchRow(r.key, { free });
                later();
              }}
              onFillCost={(part) => {
                const base = bases.find((b) => b.id === part.sell_way_id) ?? bases.find((b) => fold(b.name) === fold(part.name));
                if (base) openRow(base.key, "cost", r.key);
              }}
            />
          )}
        />
      </div>
    );
  };

  const bm = data?.assumptions;
  return (
    <div className="flex flex-col gap-4">
      {head}
      {data && (
        <>
          <section aria-label="賣法" className="rounded-xl border border-border bg-card px-[22px] py-5 max-[480px]:p-4">
            <div className="mb-1 flex flex-wrap items-baseline gap-2.5">
              <h2 className="text-[15px] font-semibold">基本賣法</h2>
              <span className="text-[11.5px] text-muted-foreground">一份就是一個單位</span>
            </div>
            <div data-section="base">{bases.map(item)}</div>
            <div className="mt-[22px] mb-1 flex flex-wrap items-baseline gap-2.5">
              <h2 className="text-[15px] font-semibold">組合賣法</h2>
              <span className="text-[11.5px] text-muted-foreground">用上面的賣法湊</span>
            </div>
            <div data-section="composed">
              {combos.length > 0 ? combos.map(item) : <p className="py-2.5 text-[12.5px] text-muted-foreground">還沒有組合</p>}
            </div>
            <div className="mt-3.5 flex flex-wrap items-center gap-x-[18px] gap-y-2.5 border-t border-border pt-3">
              <Button type="button" variant="link" className="h-auto p-0 text-[13px]" onClick={() => canLeave() && addRow("base")}>＋基本賣法</Button>
              <Button type="button" variant="link" className="h-auto p-0 text-[13px]" onClick={() => canLeave() && addRow("composed")}>＋組合賣法（例如 6 盒）</Button>
              <span className="text-[11.5px] text-muted-foreground">
                跟別的商品一起賣 →{" "}
                <Link to={`/brands/${encodeURIComponent(brandId)}/products/bundles/new`} className="font-medium text-primary hover:underline">商品頁「新增組合」</Link>
              </span>
            </div>
            {status && <p role="status" className="mt-2 text-[12.5px] text-muted-foreground">{status}</p>}
            {saveError && <p role="alert" className="mt-2 text-sm text-danger">{saveError}</p>}
          </section>

          <details className="group rounded-[10px] border border-border bg-card">
            <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-[11px] font-medium text-muted-foreground [&::-webkit-details-marker]:hidden">
              <span aria-hidden="true" className="inline-block text-base leading-none transition-transform group-open:rotate-90">›</span>
              進階：不知道成本？用同業參考值（會標示是假設）
            </summary>
            {bm && (
              <div className="flex flex-col gap-2 px-4 pb-4 text-[13px]">
                <Benchmark label="成本" source={bm.gross_margin.source_text} action="空著的成本填參考值" onFill={() => fillAssumed("cost")} />
                <Benchmark label="運費成本" source={bm.shipping_cost.source_text} action="空著的運費成本填參考值" onFill={() => fillAssumed("shipping")} />
                {show && bm.close_rate && (
                  <Benchmark label="成交率" source={bm.close_rate.source_text} action="空著的成交率填參考值" onFill={() => fillAssumed("close_rate")} />
                )}
              </div>
            )}
          </details>
        </>
      )}
      <OnboardingBar back={back}>
        {waiting && (
          <small className="text-xs text-muted-foreground">
            <Button type="button" variant="link" className="h-auto p-0 text-xs" onClick={() => openRow(waiting.key, "cost")}>{waiting.name.trim()}還沒填成本</Button>
            ，用到它的組合打平算不出來
          </small>
        )}
        <BarNext label="完成商品建檔" disabled={!data || busy} onClick={() => void finish()} />
      </OnboardingBar>
    </div>
  );
}

function Benchmark({ label, source, action, onFill }: { label: string; source: string; action: string; onFill: () => void }) {
  return (
    <div className="grid grid-cols-[80px_minmax(0,1fr)_auto] items-center gap-3 border-t border-border pt-2 first:border-t-0 first:pt-0">
      <b className="font-medium">{label}</b>
      <span className="text-xs text-muted-foreground [overflow-wrap:anywhere]">{source}</span>
      <Button type="button" variant="link" className="h-auto p-0 text-[13px]" onClick={onFill}>{action}</Button>
    </div>
  );
}
