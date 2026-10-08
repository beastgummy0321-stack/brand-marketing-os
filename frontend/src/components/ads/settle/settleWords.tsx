import type {SettleRow} from "@/lib/adsSettleApi";
import {Chip, GradeRules, GradeTermChip} from "../patterns";

/** Vocabulary only: keep the server grade and thresholds, never imply purchases for other/unknown kinds. */
export const purchaseWords = (rows: SettleRow[]) => rows.length > 0 && rows.every(row => row.result_kind === "purchase");
export const resultGradeLabel = (row: SettleRow) => row.grade === "wasted" && row.result_kind !== "purchase" ? "尚無成果" : row.grade_label;
export function SettleCostRules({rows}: {rows: SettleRow[]}) {
  return <GradeRules money={false} wastedText={purchaseWords(rows) ? undefined : "尚無成果＝花了錢仍沒有成果"} />;
}
export function SettleGradeChip({row}: {row: SettleRow}) {
  return row.grade === "wasted" && row.result_kind !== "purchase" ? <Chip tone="stop" data-grade="wasted">尚無成果</Chip> :
    <GradeTermChip grade={row.grade} label={row.grade_label} reasonCode={row.reason_code} />;
}
