import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { Skeleton } from "@/components/layout/Skeleton";
import type {
  ProductEvidence,
  ProductSellWays,
  ProductWhat,
  ProductWho,
  ReadinessCheck,
  ReadinessMissing,
  SellWayRow,
} from "@/lib/intakeProductApi";
import {
  completeProductOnboarding,
  fetchProductEvidence,
  fetchProductOnboarding,
  fetchProductSellWays,
  fetchProductWho,
} from "@/lib/intakeProductApi";
import { cn } from "@/lib/utils";
import { OnboardingStepHead, type StepNav } from "../OnboardingStepHead";
import { READINESS_STEP, newBundlePath, newProductPath } from "./ProductCard";

interface Loaded {
  /** The server's verdict (`product_readiness`): the chip says 可以投放 only when true. */
  ready: boolean;
  /** The server's checklist, printed as served (F50 Contract R). */
  checklist: ReadinessCheck[];
  /** The server's `missing` (`product_readiness`, in order; F50-I18): the title names the first. */
  missing: ReadinessMissing[];
  who: ProductWho;
  evidence: ProductEvidence;
  sellWays: ProductSellWays;
}

type LoadState = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: Loaded };

/** One checklist row: the served item (its `ok` and `required` as served), the step 「去補」 opens, the label over
 * the detail line. */
interface Row {
  key: ReadinessCheck["key"];
  step: number;
  ok: boolean;
  required: boolean;
  label: string;
  detail: string;
}

const errorText = (err: unknown) => (err instanceof Error ? err.message : "讀取失敗，請稍後再試。");
const amount = (value: number) => Math.round(value).toLocaleString("zh-TW");
const newCampaignPath = (brandId: string, sellWayId: string) =>
  `/brands/${encodeURIComponent(brandId)}/ads/new?sell_way=${encodeURIComponent(sellWayId)}`;

/** 「單盒 399（打平 249）」「三盒組 999（打平 669，組合價 省 198＋滿 NT$999 免運）」: server numbers and labels as is. */
function sellWayText(way: SellWayRow): string {
  const price = way.price === null ? "未定價" : amount(way.price);
  const be = way.break_even === null ? "未知" : amount(way.break_even);
  const offers = way.offer_labels.length ? `，${way.offer_labels.join("＋")}` : "";
  return `${way.name} ${price}（打平 ${be}${offers}）`;
}

/** The rows are the served checklist (F50 Contract R): which items there are, whether each is met and whether it
 * is required are the server's verdict, never counted here. Only the words under a met item are read from the step
 * GETs (saved values only: an AI proposal, `source: "ai"`, `id: null`, is not the product's yet). An unmet item
 * reads 「〈served label〉：還沒有」. */
function checklist(data: Loaded): Row[] {
  const painLabel = new Map(data.who.pain_options.map((o) => [o.key, o.label]));
  const groups = data.who.groups.filter((g) => g.id !== null && g.source === "saved");
  const proof = data.evidence.proof.filter((p) => p.id !== null && p.source === "saved");
  const claims = data.evidence.claims.filter((c) => c.id !== null && c.source === "saved");
  const proofLabel = new Map(data.evidence.proof_kinds.map((k) => [k.key, k.label]));
  const ways = data.sellWays.sell_ways.filter((w) => w.id !== null);
  const met: Record<ReadinessCheck["key"], { label: string; detail: string }> = {
    groups: {
      label: `誰會買：${groups.length} 群`,
      detail: groups.map((g) => `${g.who}（${g.pain_keys.map((k) => painLabel.get(k) ?? k).join("、")}）`).join("・"),
    },
    proof: {
      label: `證據 ${proof.length} 項・說法 ${claims.filter((c) => c.verdict === "ok").length} 可以講、${claims.filter((c) => c.verdict === "no").length} 不能講`,
      detail: [...new Set(proof.map((p) => proofLabel.get(p.fact_key) ?? p.fact_key))].join("、"),
    },
    sell_ways: { label: `賣法 ${ways.length} 種`, detail: ways.map(sellWayText).join("・") },
  };
  return data.checklist.map((item) => ({
    key: item.key,
    step: READINESS_STEP[item.key] ?? 1,
    ok: item.ok,
    required: item.required,
    ...(item.ok ? met[item.key] : { label: `${item.label}：還沒有`, detail: "" }),
  }));
}

/** The page title (F50-I18): 「〈商品〉建好了／可以拿它建活動了」 only when the server says `ready`; otherwise the title
 * names what is missing — the first served `missing` label (「〈商品〉還沒有顧客群」), skipping `steps` 「建檔還沒走完」
 * when a concrete item follows (this page is the step that records 完成) — else 〈商品〉建到一半. While loading, the name
 * alone. */
function heading(name: string, data: Loaded | null): { title: string; purpose?: string } {
  if (!data) return { title: name };
  if (data.ready) return { title: `${name}建好了`, purpose: "可以拿它建活動了" };
  const first = data.missing.find((m) => m.key !== "steps") ?? data.missing[0];
  return { title: `${name}${first ? first.label : "建到一半"}`, purpose: "還不能拿它建活動" };
}

/** Product onboarding `#/p5` 〈商品〉建好了 (prototype `R.p5` of `.harness/scratch/prototype/f41-onboarding/index.html`):
 * the card 「這個商品」 with its state chip and one `.chk` row per item of the server's checklist (`GET …/onboarding`
 * `ready` + `checklist`, F50 Contract R): 誰會買, 證據與說法, 賣法與價格 — the chip says 可以投放 only when the server
 * says `ready`, else 建到一半. A missing required item is a red row with 「去補」 to its step (`onGoStep`); a missing
 * optional one is yellow. The words under a met item come from the step GETs (saved values only). Then 「用它建活動 →」
 * (only when ready: the new campaign with the first sell-way preselected, `?sell_way=`), 「再建一個商品」 and
 * 「做跨商品組合」. A product whose four steps are saved but whose 完成 was not recorded is completed once on entering
 * (`POST …/onboarding/complete`, idempotent) when every required item is met, like the brand's #/b7; otherwise the
 * red rows say what is missing. */
export function ProductDoneStep({ brandId, productId, nav, what, completed, onGoStep }: {
  brandId: string;
  productId: string;
  nav: StepNav;
  what: ProductWhat;
  completed: boolean;
  onGoStep: (step: number) => void;
}) {
  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  const alive = useRef(true);

  async function read() {
    setLoad({ status: "loading" });
    try {
      const [status, who, evidence, sellWays] = await Promise.all([
        fetchProductOnboarding(brandId, productId),
        fetchProductWho(brandId, productId),
        fetchProductEvidence(brandId, productId),
        fetchProductSellWays(brandId, productId),
      ]);
      let verdict = status;
      const requiredMet = (status.checklist ?? []).every((item) => item.ok || !item.required);
      if (!status.completed && status.step >= 5 && requiredMet) verdict = await completeProductOnboarding(brandId, productId);
      const data = {
        ready: verdict.ready === true, checklist: verdict.checklist ?? [], missing: verdict.missing ?? [], who, evidence, sellWays,
      };
      if (alive.current) setLoad({ status: "ready", data });
    } catch (err) {
      if (alive.current) setLoad({ status: "error", message: errorText(err) });
    }
  }

  useEffect(() => {
    alive.current = true;
    void read();
    return () => {
      alive.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brandId, productId, completed]);

  const data = load.status === "ready" ? load.data : null;
  const firstWay = data?.ready ? data.sellWays.sell_ways.find((w) => w.id !== null)?.id ?? null : null;

  return (
    <div className="flex flex-col gap-4">
      <OnboardingStepHead {...nav} {...heading(what.name, data)} />
      <section data-slot="product-checklist" aria-labelledby="product-done-title" className="rounded-xl border border-border bg-card px-[22px] py-5">
        <div className="mb-3.5 flex flex-wrap items-center justify-between gap-3">
          <h2 id="product-done-title" className="text-[15px] font-semibold">這個商品</h2>
          {data && <StateChip ready={data.ready} />}
        </div>
        {load.status === "loading" && (
          <div className="flex flex-col gap-2">
            <Skeleton className="h-11" />
            <Skeleton className="h-11" />
            <Skeleton className="h-11" />
            <Skeleton className="h-11" />
          </div>
        )}
        {load.status === "error" && (
          <div className="flex flex-col items-start gap-2">
            <p role="alert" className="text-sm text-danger">{load.message}</p>
            <Button type="button" variant="link" className="h-auto p-0 text-[13px]" onClick={() => void read()}>重新載入</Button>
          </div>
        )}
        {data && (
          <ul>
            {checklist(data).map((row) => <CheckRow key={row.key} row={row} onGoStep={onGoStep} />)}
          </ul>
        )}
      </section>
      <div className="flex flex-wrap items-center gap-2.5">
        {firstWay ? (
          <Button asChild size="lg" className="px-[22px] font-semibold">
            <Link to={newCampaignPath(brandId, firstWay)}>用它建活動 →</Link>
          </Button>
        ) : (
          <Button type="button" size="lg" className="px-[22px] font-semibold" busy={load.status === "loading"} disabledReason={!data ? "先重試讀取商品資料" : !data.ready ? "先完成商品資料，才能用它建立活動" : "先保存一個賣法，才能用它建立活動"}>用它建活動 →</Button>
        )}
        <Button asChild variant="outline" size="lg" className="font-semibold">
          <Link to={newProductPath(brandId)}>再建一個商品</Link>
        </Button>
        <Button asChild variant="outline" size="lg" className="font-semibold">
          <Link to={newBundlePath(brandId)}>做跨商品組合</Link>
        </Button>
      </div>
    </div>
  );
}

/** Prototype `.chip.ok` 可以投放 / `.chip.warn` 建到一半 (the words of the products page's card chip). */
function StateChip({ ready }: { ready: boolean }) {
  return (
    <span
      data-slot="chip"
      data-tone={ready ? "ok" : "warn"}
      className={cn(
        "inline-flex shrink-0 items-center rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap",
        ready ? "bg-zone-ok text-success" : "bg-zone-watch text-warning",
      )}
    >
      {ready ? "可以投放" : "建到一半"}
    </span>
  );
}

/** Prototype `chk(c, t, d, a)`: green ✓, red ! (a missing required item) or yellow ! (`i.y`, a missing optional
 * one), the label over the detail, 「去補」 on a missing item. Every row has the top rule (in `R.p5` the head sits
 * above the first row). */
function CheckRow({ row, onGoStep }: { row: Row; onGoStep: (step: number) => void }) {
  const state = row.ok ? "green" : row.required ? "red" : "yellow";
  return (
    <li data-slot="check-row" data-state={state} className="grid grid-cols-[28px_minmax(0,1fr)_auto] items-center gap-3 border-t border-border py-[11px]">
      <span
        aria-hidden="true"
        className={cn(
          "grid size-6 place-items-center rounded-full text-xs font-bold text-white",
          state === "green" ? "bg-success" : state === "red" ? "bg-danger" : "bg-warning",
        )}
      >
        {row.ok ? "✓" : "!"}
      </span>
      <div className="min-w-0">
        <b className="font-semibold">{row.label}</b>
        {row.detail && <p className="text-[11.5px] text-muted-foreground">{row.detail}</p>}
      </div>
      {!row.ok && (
        <Button type="button" variant="link" className="h-auto p-0 text-[13px]" onClick={() => onGoStep(row.step)}>去補</Button>
      )}
    </li>
  );
}
