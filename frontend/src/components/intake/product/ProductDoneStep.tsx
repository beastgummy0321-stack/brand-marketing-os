import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { Skeleton } from "@/components/layout/Skeleton";
import type { ProductEvidence, ProductSellWays, ProductWhat, ProductWho, SellWayRow } from "@/lib/intakeProductApi";
import {
  completeProductOnboarding,
  fetchProductEvidence,
  fetchProductOnboarding,
  fetchProductSellWays,
  fetchProductWho,
} from "@/lib/intakeProductApi";
import { cn } from "@/lib/utils";
import { OnboardingStepHead, type StepNav } from "../OnboardingStepHead";
import { newBundlePath, newProductPath } from "./ProductCard";

interface Loaded {
  /** The status step (1–5); a finished product reads 5. */
  step: number;
  completed: boolean;
  who: ProductWho;
  evidence: ProductEvidence;
  sellWays: ProductSellWays;
}

type LoadState = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: Loaded };

/** One checklist row: its step, whether that part is saved, the label over the detail line. */
interface Row {
  step: number;
  ok: boolean;
  label: string;
  detail: string;
}

const errorText = (err: unknown) => (err instanceof Error ? err.message : "讀取失敗，請稍後再試。");
const amount = (value: number) => Math.round(value).toLocaleString("zh-TW");
const newCampaignPath = (brandId: string, sellWayId: string) =>
  `/brands/${encodeURIComponent(brandId)}/ads/new?sell_way=${encodeURIComponent(sellWayId)}`;

/** Prototype `.chk` rows: 一句話、成分、差異 name the parts of step 1. */
const WHAT_PARTS = [
  ["intro", "一句話"],
  ["mechanism", "成分"],
  ["difference", "差異"],
] as const;

/** 「單盒 399（打平 249）」「三盒組 999（打平 669，組合價 省 198＋滿 NT$999 免運）」: server numbers and labels as is. */
function sellWayText(way: SellWayRow): string {
  const price = way.price === null ? "未定價" : amount(way.price);
  const be = way.break_even === null ? "未知" : amount(way.break_even);
  const offers = way.offer_labels.length ? `，${way.offer_labels.join("＋")}` : "";
  return `${way.name} ${price}（打平 ${be}${offers}）`;
}

/** Only saved parts count: an AI proposal (`source: "ai"`, `id: null`) is not the product's yet. A part is missing
 * when its step is not saved yet (a product being built) or nothing of it is saved. */
function checklist(what: ProductWhat, data: Loaded): Row[] {
  const saved = (step: number) => data.completed || data.step > step;
  const whatParts = WHAT_PARTS.filter(([key]) => what[key].source === "saved" && what[key].value.trim()).map(([, label]) => label);
  const painLabel = new Map(data.who.pain_options.map((o) => [o.key, o.label]));
  const groups = data.who.groups.filter((g) => g.id !== null && g.source === "saved");
  const proof = data.evidence.proof.filter((p) => p.id !== null && p.source === "saved");
  const claims = data.evidence.claims.filter((c) => c.id !== null && c.source === "saved");
  const proofLabel = new Map(data.evidence.proof_kinds.map((k) => [k.key, k.label]));
  const ways = data.sellWays.sell_ways.filter((w) => w.id !== null);
  const rows: Row[] = [
    { step: 1, ok: saved(1) && whatParts.length > 0, label: "商品是什麼", detail: whatParts.join("、") },
    {
      step: 2,
      ok: saved(2) && groups.length > 0,
      label: `誰會買：${groups.length} 群`,
      detail: groups.map((g) => `${g.who}（${g.pain_keys.map((k) => painLabel.get(k) ?? k).join("、")}）`).join("・"),
    },
    {
      step: 3,
      ok: saved(3) && proof.length + claims.length > 0,
      label: `證據 ${proof.length} 項・說法 ${claims.filter((c) => c.verdict === "ok").length} 可以講、${claims.filter((c) => c.verdict === "no").length} 不能講`,
      detail: [...new Set(proof.map((p) => proofLabel.get(p.fact_key) ?? p.fact_key))].join("、"),
    },
    { step: 4, ok: saved(4) && ways.length > 0, label: `賣法 ${ways.length} 種`, detail: ways.map(sellWayText).join("・") },
  ];
  const missing = ["商品是什麼", "誰會買", "證據與說法", "賣法"];
  return rows.map((row) => (row.ok ? row : { ...row, label: `${missing[row.step - 1]}：還沒有`, detail: "" }));
}

/** Product onboarding `#/p5` 〈商品〉建好了 (prototype `R.p5` of `.harness/scratch/prototype/f41-onboarding/index.html`):
 * the card 「這個商品」 with its state chip (可以投放 / 建到一半) and one `.chk` row per step -- 商品是什麼 (from the shell's
 * `what`), 誰會買, 證據與說法, 賣法 (read here from the step GETs; only saved values count). A missing part is a red row
 * with 「去補」 to its step (`onGoStep`). Then 「用它建活動 →」 (the new campaign with the first sell-way preselected,
 * `?sell_way=`), 「再建一個商品」 and 「做跨商品組合」. A product whose four steps are saved but whose 完成 was not
 * recorded is completed once on entering (`POST …/onboarding/complete`, idempotent), like the brand's #/b7. */
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
        completed ? Promise.resolve({ step: 5, completed: true }) : fetchProductOnboarding(brandId, productId),
        fetchProductWho(brandId, productId),
        fetchProductEvidence(brandId, productId),
        fetchProductSellWays(brandId, productId),
      ]);
      let { step, completed: done } = status;
      if (!done && step >= 5) ({ step, completed: done } = await completeProductOnboarding(brandId, productId));
      if (alive.current) setLoad({ status: "ready", data: { step, completed: done, who, evidence, sellWays } });
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
  const firstWay = data?.completed ? data.sellWays.sell_ways.find((w) => w.id !== null)?.id ?? null : null;

  return (
    <div className="flex flex-col gap-4">
      <OnboardingStepHead {...nav} title={`${what.name}建好了`} purpose="可以拿它建活動了" />
      <section data-slot="product-checklist" aria-labelledby="product-done-title" className="rounded-xl border border-border bg-card px-[22px] py-5">
        <div className="mb-3.5 flex flex-wrap items-center justify-between gap-3">
          <h2 id="product-done-title" className="text-[15px] font-semibold">這個商品</h2>
          {data && <StateChip ready={data.completed} />}
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
            {checklist(what, data).map((row) => <CheckRow key={row.step} row={row} onGoStep={onGoStep} />)}
          </ul>
        )}
      </section>
      <div className="flex flex-wrap items-center gap-2.5">
        {firstWay ? (
          <Button asChild size="lg" className="px-[22px] font-semibold">
            <Link to={newCampaignPath(brandId, firstWay)}>用它建活動 →</Link>
          </Button>
        ) : (
          <Button type="button" size="lg" className="px-[22px] font-semibold" disabled>用它建活動 →</Button>
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

/** Prototype `chk(c, t, d, a)`: green ✓ or red !, the label over the detail, 「去補」 on a missing part. Every row has
 * the top rule (in `R.p5` the head sits above the first row). */
function CheckRow({ row, onGoStep }: { row: Row; onGoStep: (step: number) => void }) {
  return (
    <li data-slot="check-row" data-state={row.ok ? "green" : "red"} className="grid grid-cols-[28px_minmax(0,1fr)_auto] items-center gap-3 border-t border-border py-[11px]">
      <span aria-hidden="true" className={cn("grid size-6 place-items-center rounded-full text-xs font-bold text-white", row.ok ? "bg-success" : "bg-danger")}>
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
