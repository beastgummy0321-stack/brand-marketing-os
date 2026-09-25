/** Feature F29 Contract K: CSV built in the browser from the numbers a screen already shows (no endpoint).
 * UTF-8 with a BOM (so Excel opens Chinese text correctly), CRLF line ends, RFC 4180 quoting.
 * `null`/`undefined` is an empty cell — an unknown number is never written as 0. */
export type CsvCell = string | number | null | undefined;

function cell(value: CsvCell): string {
  if (value === null || value === undefined) return "";
  const text = typeof value === "number" ? (Number.isFinite(value) ? String(value) : "") : value;
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
