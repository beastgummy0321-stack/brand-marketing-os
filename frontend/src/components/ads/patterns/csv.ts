/** Feature F29 Contract K: CSV built in the browser from the numbers a screen already shows (no endpoint).
 * UTF-8 with a BOM (so Excel opens Chinese text correctly), CRLF line ends, RFC 4180 quoting.
 * `null`/`undefined` is an empty cell — an unknown number is never written as 0. */
import { formatAmount } from "./Chip";

export type CsvCell = string | number | null | undefined;

/** F47-I06: the ONE rule for a per-sale money figure (cost per purchase／per result) on every ads screen — rounded to
 * whole yuan, never floored, so home, performance, A/B, settle and strategy print the same 2,015 for 2,014.6.
 * `null` (unknown) stays `null`; the caller prints its own unknown word. Lives beside the CSV number rule. */
export function perSaleAmount(value: number | null | undefined): string | null {
  return value === null || value === undefined || !Number.isFinite(value) ? null : formatAmount(Math.round(value));
}

/** F47-I06: a number is written rounded to 2 decimals, without float tails (3286.2400000000002 → 3286.24) and without
 * padding (1440 stays 1440). */
function numberText(value: number): string {
  return Number.isFinite(value) ? String(Math.round(value * 100) / 100) : "";
}

function cell(value: CsvCell): string {
  if (value === null || value === undefined) return "";
  const text = typeof value === "number" ? numberText(value) : value;
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/** The CSV text (without BOM): rows joined by CRLF, ending with CRLF. */
export function toCsv(rows: CsvCell[][]): string {
  return rows.map((row) => row.map(cell).join(",")).join("\r\n") + "\r\n";
}

/** Saves `rows` as `<name>.csv` through a temporary download link. */
export function downloadCsv(name: string, rows: CsvCell[][]): void {
  const blob = new Blob(["﻿", toCsv(rows)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name.toLowerCase().endsWith(".csv") ? name : `${name}.csv`;
  link.style.display = "none";
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
