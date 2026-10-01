import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/layout/ui/button";
import type { AssumptionField, ProductSellWays, SellWayInput, SellWayMoney, SellWayRow } from "@/lib/intakeProductApi";
import { completeProductOnboarding, fetchProductSellWays, saveProductSellWays } from "@/lib/intakeProductApi";
import { BarNext, OnboardingBar, OnboardingStepHead, type BarBack, type StepNav } from "../OnboardingStepHead";
import { draftFromMoney, emptyDraft, moneyErrors, moneyInput, SellWayTable, type MoneyDraft } from "./SellWayTable";

interface Row {
  key: string;
  id: string | null;
  name: string;
  /** Units of this product; editable only on a row added or proposed on this visit. */
  qty: string;
  draft: MoneyDraft;
  /** The server's numbers after the last save; null = not saved yet. */
  money: SellWayMoney | null;
  /** The 內容 cell of a saved row (「綜合維他命軟糖 ×3」). */
  content: string;
  /** Added or proposed on this visit: its × takes it out again. */
  fresh: boolean;
  touched: boolean;
}

const errorText = (err: unknown) => (err instanceof Error ? err.message : "儲存失敗，請稍後再試。");
const contentOf = (w: SellWayRow) => w.components.map((c) => `${c.name} ×${c.qty}`).join("、");
const qtyOf = (raw: string): number | null => (/^\d+$/.test(raw.trim()) && Number(raw) > 0 ? Number(raw) : null);

function rowValid(row: Row, showCloseRate: boolean): boolean {
  return row.name.trim() !== "" && qtyOf(row.qty) !== null && Object.keys(moneyErrors(row.draft, showCloseRate)).length === 0;
}

function toInput(rows: Row[], showCloseRate: boolean): SellWayInput[] {
  return rows.map((r) => ({ id: r.id, name: r.name.trim(), qty: qtyOf(r.qty) ?? 1, ...moneyInput(r.draft, showCloseRate) }));
}

/** Product onboarding `#/p4` 怎麼賣、賣多少 (prototype `R.p4` of `.harness/scratch/prototype/f41-onboarding/index.html`):
 * one `SellWayTable` row per sell-way of this product (saved ones, else the product-page read's proposals),
 * 「＋新增賣法」, the pointer to 「新增組合」, the formula line and the 「不知道成本？」 reference-value fold.
 *
 * Every save sends the whole list through `PUT …/onboarding/sell-ways` (raw inputs only); the table then shows the
 * server's 打平線, derived 原價／成本 and offers. A row saves when focus leaves it and every row is valid; nothing is
 * computed here. 完成商品建檔 saves what is left, then `POST …/onboarding/complete`, and moves on only after both
 * succeeded. */
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
  const [saveError, setSaveError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const uid = useRef(0);
  const rowsRef = useRef<Row[]>([]);
  rowsRef.current = rows;
  /** The last list the server confirmed (without ids): an unchanged list is not sent again. */
  const savedSig = useRef<string | null>(null);
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    fetchProductSellWays(brandId, productId)
      .then((loaded) => {
        if (!alive.current) return;
        setData(loaded);
        const list = loaded.sell_ways.map((w) => fromServer(w));
        setRows(list.length > 0 ? list : [blankRow()]);
        const saved = loaded.sell_ways.filter((w) => w.id);
        if (saved.length === loaded.sell_ways.length && saved.length > 0) savedSig.current = sig(list, loaded.show_close_rate);
      })
      .catch((err: unknown) => alive.current && setLoadError(err instanceof Error ? err.message : "讀取失敗，請稍後再試。"));
    return () => {
      alive.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brandId, productId]);

  function fromServer(w: SellWayRow): Row {
    return {
      key: `sw${uid.current++}`,
      id: w.id,
      name: w.name,
      qty: String(w.qty),
      draft: draftFromMoney(w),
      // A proposal from the product page is not saved: nothing is derived for it yet.
      money: w.id ? w : null,
      content: contentOf(w),
      fresh: w.id === null,
      touched: false,
    };
  }

  function blankRow(): Row {
    return { key: `sw${uid.current++}`, id: null, name: "", qty: "1", draft: emptyDraft(), money: null, content: "", fresh: true, touched: false };
  }

  const show = data?.show_close_rate ?? false;
  const sig = (list: Row[], closeRate: boolean) => JSON.stringify(toInput(list, closeRate).map(({ id: _id, ...rest }) => rest));

  /** Saves the current list when it is valid and changed; resolves true once the server holds exactly these rows. */
  function persist(): Promise<boolean> {
    const run = queue.current.then(async () => {
      const current = rowsRef.current;
      if (current.length === 0 || !current.every((r) => rowValid(r, show))) return false;
      const signature = sig(current, show);
      if (signature === savedSig.current && current.every((r) => r.id)) return true;
      const sent = current.map((r) => ({ key: r.key, id: r.id, name: r.name.trim().toLowerCase() }));
      try {
        const res = await saveProductSellWays(brandId, productId, toInput(current, show));
        savedSig.current = signature;
        const byId = new Map(res.sell_ways.filter((w) => w.id).map((w) => [w.id as string, w]));
        const byName = new Map(res.sell_ways.map((w) => [w.name.trim().toLowerCase(), w]));
        const serverFor = new Map(sent.map((s) => [s.key, (s.id && byId.get(s.id)) || byName.get(s.name)]));
        if (alive.current) {
          setSaveError(null);
          setRows((prev) => prev.map((r) => {
            const w = serverFor.get(r.key);
            return w ? { ...r, id: w.id, money: w, content: contentOf(w) } : r;
          }));
        }
        return true;
      } catch (err) {
        if (alive.current) setSaveError(errorText(err));
        return false;
      }
    });
    queue.current = run.catch(() => undefined);
    return run;
  }

  const patchRow = (key: string, patch: Partial<Row>) => setRows((prev) => prev.map((r) => (r.key === key ? { ...r, ...patch } : r)));

  function onRowBlur(key: string) {
    patchRow(key, { touched: true });
    // Let the state settle (the last keystroke and `touched`) before reading the rows.
    window.setTimeout(() => void persist(), 0);
  }

  async function finish() {
    setRows((prev) => prev.map((r) => ({ ...r, touched: true })));
    if (!rowsRef.current.every((r) => rowValid(r, show))) return;
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

  /** 「不知道？用同業參考值」 (F05 rule 3): fills the empty field of every row and flags it 假設. */
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
        // A cost the server already derives (「3 件成本相加」) is not unknown.
        if (r.money?.cost_derived || !(price > 0)) return r;
        value = String(Math.round(price * (1 - bm.gross_margin.value)));
      }
      if (value === null) return r;
      return { ...r, draft: { ...r.draft, [field]: value, assumptions: [...r.draft.assumptions.filter((a) => a !== field), field] } };
    }));
    window.setTimeout(() => void persist(), 0);
  }

  const head = <OnboardingStepHead {...nav} title="怎麼賣、賣多少" purpose="每一種賣法各一列；優惠直接從這裡算，不用另外設" />;

  if (loadError) {
    return (
      <div className="flex flex-col gap-4">
        {head}
        <p role="alert" className="text-sm text-danger">{loadError}</p>
        <OnboardingBar back={back} />
      </div>
    );
  }

  const productName = data?.sell_ways.flatMap((w) => w.components).find((c) => c.product_id === productId)?.name
    ?? nav.crumb[nav.crumb.length - 1]?.label ?? "";
  const tableRows = rows.map((r) => ({
    key: r.key,
    draft: r.draft,
    money: r.money,
    name: r.name,
    showErrors: r.touched,
    onRemove: r.fresh && rows.length > 1 ? () => removeRow(r.key) : undefined,
    content: r.fresh ? (
      <span className="flex flex-wrap items-center gap-1">
        <span className="[overflow-wrap:anywhere]">{productName}</span>
        <span className="whitespace-nowrap">×</span>
        <input
          aria-label={`${r.name.trim() || "新的賣法"}的數量`}
          inputMode="numeric"
          aria-invalid={r.touched && qtyOf(r.qty) === null ? true : undefined}
          className="w-12 rounded-md border border-input bg-card px-2 py-1.5 text-[13px] text-foreground tabular-nums focus:border-primary focus:shadow-[0_0_0_3px_var(--color-accent)] focus:outline-none aria-invalid:border-danger"
          value={r.qty}
          onChange={(e) => patchRow(r.key, { qty: e.target.value })}
        />
        {r.touched && qtyOf(r.qty) === null && <span role="alert" className="w-full text-[11.5px] text-danger">數量要是正整數</span>}
      </span>
    ) : (
      r.content || `${productName} ×${r.qty}`
    ),
  }));

  function removeRow(key: string) {
    setRows((prev) => prev.filter((r) => r.key !== key));
    window.setTimeout(() => void persist(), 0);
  }

  const bm = data?.assumptions;
  return (
    <div className="flex flex-col gap-4">
      {head}
      {data && (
        <>
          <section aria-label="賣法" className="rounded-xl border border-border bg-card px-[22px] py-5">
            <SellWayTable
              rows={tableRows}
              showCloseRate={show}
              onDraft={(key, patch) => setRows((prev) => prev.map((r) => (r.key === key ? { ...r, draft: { ...r.draft, ...patch } } : r)))}
              onName={(key, name) => patchRow(key, { name })}
              onRowBlur={onRowBlur}
            />
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <Button type="button" variant="link" className="h-auto p-0" onClick={() => setRows((prev) => [...prev, blankRow()])}>
                ＋新增賣法（例如六盒組）
              </Button>
              <span className="text-xs text-muted-foreground">跟別的商品一起賣，到商品頁「新增組合」</span>
            </div>
            <p className="mt-2.5 text-xs text-muted-foreground">
              {show ? "打平線＝（售價 − 成本 − 運費成本）× 成交率" : "打平線＝售價 − 成本 − 運費成本"}
              ；每筆上限預設＝打平線，想更保守就改低。優惠：原價比售價高＝組合價；品牌政策的優惠自動算進來。
            </p>
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
