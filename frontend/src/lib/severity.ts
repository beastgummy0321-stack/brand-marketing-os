import type { AlertSeverity } from "./api";

/** 嚴重度顏色／文字對照（單一權威）：駕駛艙異常警示區（票 05）與收件匣（票 B1-inbox，
 * 契約 S2.4）共用同一組，不讓伺服器多回一個 `severity_label` 欄位、也不各自重刻一份。 */
export const SEVERITY_LABEL: Record<AlertSeverity, string> = {
  money_loss: "金額損失",
  irreversible: "不可逆",
  rule_warning: "規則警示",
  informational: "資訊性",
};

export const SEVERITY_DOT_CLASS: Record<AlertSeverity, string> = {
  money_loss: "bg-danger",
  irreversible: "bg-alert-irreversible",
  rule_warning: "bg-warning",
  informational: "bg-muted-foreground",
};
