/** F51 Contract F (W16) — numbers carry their basis. `app/core/figures.py::BASES` is the one table of bases
 * (its docstring is the authority); `GET /api/figures` serves it and this module reads it once per session.
 *
 * - `useFigureBases()` — the basis table (`{code: {label, formula, unit}}`), or `undefined` while it loads (a
 *   `Figure` then prints its value without a caption). react-query, `staleTime: Infinity`: one read per session.
 * - `roasAtCap(price, cap)` — the one browser money ratio: ROAS 參考 for a cap being typed (`roas_at_cap`,
 *   售價 ÷ 每筆上限), rounded once to 2 decimals. Saved caps print the served figure.
 * - `roasOf(revenue, spend)` — `roas_all_spend` of imported (native) rows aggregated in the browser (the rows are
 *   served raw by F49 Contract D); any unknown part nulls it — unknown is never 0.
 * - `formatFigure(unit, value, currency)` — a value printed by its basis unit, through `lib/format.ts`.
 *
 * No other file under `components/ads/**` divides by spend／cap or multiplies price × results
 * (`lib/figureGuards.test.ts` rule `money-ratio`). */
import { useQuery } from "@tanstack/react-query";
import { formatCount, formatMoney, formatRoas } from "./format";
import { apiFetch, readJson } from "./http";

export type FigureUnit = "ratio" | "money" | "count";

export interface FigureBasis {
  /** The caption printed beside the value (保守, 樂觀, 平台回報 …). */
  label: string;
  /** How it is computed, shown behind the `?` tooltip. */
  formula: string;
  unit: FigureUnit;
}

export type FigureBases = Record<string, FigureBasis>;

export const FIGURE_BASES_KEY = ["figure-bases"] as const;

export async function getFigureBases(): Promise<FigureBases> {
  const res = await apiFetch("/api/figures");
  const body = await readJson<{ bases: FigureBases }>(res, "數字口徑讀取失敗，請重新整理再試一次。");
  return body.bases;
}

/** The basis table, or `undefined` while it loads or when the read failed (values still print, without caption). */
export function useFigureBases(): FigureBases | undefined {
  const query = useQuery({
    queryKey: FIGURE_BASES_KEY,
    queryFn: getFigureBases,
    staleTime: Infinity,
    gcTime: Infinity,
  });
  return query.data;
}

/** Price ÷ cap, rounded once to 2 decimals; `null` when either is unknown or the cap is not positive. */
export function roasAtCap(price: number | null | undefined, cap: number | null | undefined): number | null {
  if (price == null || cap == null || !Number.isFinite(price) || !Number.isFinite(cap) || cap <= 0) return null;
  return Math.round((price / cap) * 100) / 100;
}

/** Revenue ÷ spend of imported rows; `null` when revenue is untracked (null), spend is unknown or zero. */
export function roasOf(revenue: number | null | undefined, spend: number | null | undefined): number | null {
  if (revenue == null || spend == null || !Number.isFinite(revenue) || !Number.isFinite(spend) || spend <= 0) return null;
  return revenue / spend;
}

/** A known value printed by its unit: money with its currency, a ratio as `2.10x`, a count with separators. */
export function formatFigure(unit: FigureUnit | undefined, value: number, currency?: string | null): string {
  if (unit === "money") return currency ? formatMoney(value, currency) : Math.round(value).toLocaleString("zh-TW");
  if (unit === "count") return formatCount(value);
  return formatRoas(value);
}
