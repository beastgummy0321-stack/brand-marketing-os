import { formatCurrency } from "@/lib/format";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { ApiResponseError } from "@/lib/http";
import type { AssumptionField, ProductSellWays, SellWayInput, SellWayRow } from "@/lib/intakeProductApi";
import { completeProductOnboarding, fetchProductSellWays, saveProductSellWays } from "@/lib/intakeProductApi";
import { BarNext, OnboardingBar, OnboardingStepHead, type BarBack, type StepNav } from "../OnboardingStepHead";
import { SellWayContents, type ContentItem } from "./SellWayContents";
import { SellWayEditor, SellWaySummary } from "./SellWayEditor";
import { adoptAssumedCost, draftFromMoney, emptyDraft, PriceBlock, stepMoneyInput, type MoneyDraft, type RowErrors } from "./SellWayTable";

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
 * Every save sends the whole list through `PUT …/onboarding/sell-ways` (raw inputs as typed; composed rows name their
 * bases; no `qty`): when focus leaves an editor field, on 「完成」, on a contents / 免運 change and on delete. Every row
 * the user typed something into is sent; the page keeps no input rule of its own (F50 Contract I): the server refuses
 * the whole list naming each field (`field_errors` `sell_ways.{i}.{field}`), and a row shows its sentences under its
 * fields once 「完成」 / 完成商品建檔 was pressed for it. The page then shows the server's numbers (derived 售價 / 原價 /
 * 成本 labelled 推算, 打平, offer sentences, the bases a cost waits for, an assumed cost); nothing is computed here.
 * 完成商品建檔 saves what is left, then `POST …/onboarding/complete`, and moves on only after both succeeded. */
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
  /** The last refusal's sentences by row key, field keys without the `sell_ways.{i}.` prefix. */
  const [rowErrors, setRowErrors] = useState<Record<string, RowErrors>>({});
  const rowErrorsRef = useRef<Record<string, RowErrors>>({});
  const [busy, setBusy] = useState(false);
  const uid = useRef(0);
  const rowsRef = useRef<Row[]>([]);
  rowsRef.current = rows;
  /** The last list the server confirmed (without ids): an unchanged list is not sent again. */
  const savedSig = useRef<string | null>(null);
  /** The last list the server refused field by field: not sent again unchanged. */
  const refusedSig = useRef<string | null>(null);
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
      ...(r.shape === "composed" ? { components: r.items.map((it) => ({ base: names.get(it.base) ?? "", qty: it.qty })) } : {}),
    }));
  }

  /** A row the user has typed nothing into yet (added on this visit, never saved): not sent. */
  const untouched = (r: Row) => r.id === null && r.server === null && !r.name.trim() && r.items.length === 0 && !r.draft.price.trim();

  /** The rows a save sends: every row except an untouched new one. null = nothing to send. */
  function sendable(list: Row[]): Row[] | null {
    const out = list.filter((r) => !untouched(r));
    return out.length > 0 ? out : null;
  }

  /** The server's `field_errors` (`sell_ways.{i}.{field}`) by the key of the row sent at index i. */
  function errorsByRow(sent: Row[], fieldErrors: Record<string, string>): Record<string, RowErrors> {
    const out: Record<string, RowErrors> = {};
    for (const [key, sentence] of Object.entries(fieldErrors)) {
      const m = /^sell_ways\.(\d+)\.(.+)$/.exec(key);
      const row = m ? sent[Number.parseInt(m[1], 10)] : undefined;
      if (m && row) out[row.key] = { ...out[row.key], [m[2]]: sentence };
    }
    return out;
  }

  /** Saves the list when it changed; resolves the server's list (true = nothing changed), or null (refused / failed:
   * the refusal's sentences are kept by row, shown once that row was tried). */
  function persist(): Promise<ProductSellWays | null | true> {
    const run = queue.current.then(async (): Promise<ProductSellWays | null | true> => {
      const current = sendable(rowsRef.current);
      if (current === null) return null;
      const signature = sig(current, show);
      if (signature === savedSig.current && current.every((r) => r.id)) return true;
      // The same list the server just refused field by field: its answer stands (kept in `rowErrors`).
      if (signature === refusedSig.current) return null;
      const sent = current.map((r) => ({ key: r.key, id: r.id, name: fold(r.name) }));
      try {
        const res = await saveProductSellWays(brandId, productId, toInput(current, show));
        const byId = new Map(res.sell_ways.filter((w) => w.id).map((w) => [w.id as string, w]));
        const byName = new Map(res.sell_ways.map((w) => [fold(w.name), w]));
        const serverFor = new Map(sent.map((s) => [s.key, (s.id && byId.get(s.id)) || byName.get(s.name)]));
        // A receipt acknowledges the submitted snapshot, not edits made while it was pending.
        const acknowledged = current.map((r) => {
          const w = serverFor.get(r.key);
          return w ? { ...r, id: w.id, draft: adoptAssumedCost(r.draft, w) } : r;
        });
        // The server's view joins each row; a cost it assumed becomes the input's value.
        const next = rowsRef.current.map((r) => {
          const w = serverFor.get(r.key);
          return w ? { ...r, id: w.id, server: w, draft: adoptAssumedCost(r.draft, w) } : r;
        });
        savedSig.current = sig(acknowledged, show);
        if (alive.current) {
          setSaveError(null);
          rowErrorsRef.current = {};
          refusedSig.current = null;
          setRowErrors({});
          rowsRef.current = next;
          setRows(next);
        }
        return res;
      } catch (err) {
        if (alive.current) {
          const keyed = err instanceof ApiResponseError ? errorsByRow(current, err.fieldErrors) : {};
          rowErrorsRef.current = keyed;
          refusedSig.current = Object.keys(keyed).length > 0 ? signature : null;
          setRowErrors(keyed);
          setSaveError(Object.keys(keyed).length > 0 ? null : errorText(err));
        }
        return null;
      }
    });
    queue.current = run.catch(() => undefined);
    return run;
  }

  /** After a refused save: the rows it names are shown as tried (their sentences under their fields); the first one
   * opens. Returns false when the refusal named no row (its sentence is the page's `saveError`). */
  function showRefusal(): boolean {
    const named = rowsRef.current.filter((r) => rowErrorsRef.current[r.key]);
    if (named.length === 0) return false;
    setTried((prev) => new Set([...prev, ...named.map((r) => r.key)]));
    setOpen(named[0].key);
    setStatus(named.length > 1 || named[0].key !== open
      ? `「${named[0].name.trim() || "還沒取名的賣法"}」還有欄位要改，紅字的地方`
      : "還有欄位要改，紅字的地方");
    return true;
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

  function openRow(key: string, field = "name", from: string | null = null) {
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
    if (!row) return;
    setBusy(true);
    const res = await persist();
    if (alive.current) setBusy(false);
    if (!alive.current) return;
    if (!res) {
      showRefusal();
      return;
    }
    const back = ret;
    setRet(null);
    setPicking(null);
    if (back) {
      const target = rowsRef.current.find((r) => r.key === back);
      const w = target && res !== true ? res.sell_ways.find((s) => s.id === target.id) : target?.server;
      setOpen(back);
      setFocus(`${back}-name`);
      setStatus(w?.break_even != null
        ? w.break_even > 0
          ? `「${w.name}」的打平算出來了：每筆最多花 ${formatCurrency(w.break_even)}`
          : `「${w.name}」的打平算出來了：${formatCurrency(w.break_even)}，${w.break_even < 0 ? "未投廣告已虧損，" : ""}沒有可用廣告空間`
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
    setBusy(true);
    try {
      if (!(await persist())) {
        if (alive.current) showRefusal();
        return;
      }
      await completeProductOnboarding(brandId, productId);
      onNext();
    } catch (err) {
      if (alive.current) setSaveError(errorText(err));
    } finally {
      if (alive.current) setBusy(false);
    }
  }

  /** 「不知道？用同業參考值」 (F05 rule 3): flags the empty field of every row 假設. 運費 and 成交率 copy the served
   * reference value (成交率 is a percent, as served); a base row's cost is left empty and the save returns the number the
   * server derived from its price (whole(price × (100 − 45) / 100)) — the page never multiplies. A composed row's cost
   * comes from its bases; it is not flagged. */
  function fillAssumed(field: AssumptionField) {
    if (!data) return;
    const bm = data.assumptions;
    const served = field === "shipping" ? bm.shipping_cost : field === "close_rate" ? bm.close_rate : undefined;
    const next = rowsRef.current.map((r) => {
      if (r.draft[field] !== "" || untouched(r)) return r;
      if (field === "cost" && r.shape === "composed") return r;
      if (field !== "cost" && !served) return r;
      const value = field === "cost" ? "" : String(served!.value);
      return { ...r, draft: { ...r.draft, [field]: value, assumptions: [...r.draft.assumptions.filter((a) => a !== field), field] } };
    });
    rowsRef.current = next;
    setRows(next);
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
    // The server's numbers of the base (the last save); a base not saved yet has none.
    price: b.server?.price ?? null,
    cost: b.server ? b.server.cost : undefined,
  }));
  /** Composed rows (by name) that hold a base: the server's `used_by` plus the ones on the page. */
  const usersOf = (b: Row) => [...new Set([...(b.server?.used_by ?? []), ...combos.filter((c) => c.items.some((it) => it.base === b.key)).map((c) => c.name.trim())])];
  const baseNoCost = (b: Row) => b.draft.cost.trim() === "" && b.server?.cost == null;
  const waiting = bases.find((b) => baseNoCost(b) && combos.some((c) => c.items.some((it) => it.base === b.key)));

  const item = (r: Row) => {
    const errors: RowErrors = tried.has(r.key) ? rowErrors[r.key] ?? {} : {};
    if (open !== r.key) {
      return (
        <SellWaySummary key={r.key} name={r.name} shape={r.shape} numbers={r.server} typedPrice={r.draft.price}
          content={r.shape === "base" ? "一份" : r.items.map((it) => `${nameOf(it.base)} × ${it.qty}`).join(" ＋ ") || "還沒放東西"}
          costMissing={r.shape === "base" && baseNoCost(r)} onEdit={() => openRow(r.key)} />
      );
    }
    const qtyBad = r.shape === "composed" && r.items.some((it) => it.qty.trim() === "");
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
          showErrors={tried.has(r.key)}
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
              errors={errors}
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
              errors={errors}
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
        {errors.name && r.name.trim() && <p role="alert" className="mt-1 text-[11.5px] text-danger">{errors.name}</p>}
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
              <Button type="button" variant="link" className="h-auto p-0 text-[13px]" onClick={() => addRow("base")}>＋基本賣法</Button>
              <Button type="button" variant="link" className="h-auto p-0 text-[13px]" onClick={() => addRow("composed")}>＋組合賣法（例如 6 盒）</Button>
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
        <BarNext label="完成商品建檔" busy={!data || busy} onClick={() => void finish()} />
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
