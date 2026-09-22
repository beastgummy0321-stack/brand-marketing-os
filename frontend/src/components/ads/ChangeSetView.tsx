import { Link } from "react-router-dom";
import { useState } from "react";
import { AlertTriangle, CheckCircle2, Clock, Info } from "lucide-react";
import { Button } from "@/components/layout/ui/button";
import { Badge } from "@/components/layout/ui/badge";
import { Input } from "@/components/layout/ui/input";
import { Textarea } from "@/components/layout/ui/textarea";
import type { ChangeItem, ChangeSet, SettingValues } from "@/lib/adsChangeApi";
import { Disclosure } from "./patterns/Disclosure";
import { kindLabel, targetLabel } from "./ChangeComposer";

const verificationLabels: Record<ChangeItem["verification_state"], string> = {
  pending: "尚未回報", reported: "已自行回報，待核對", confirmed: "設定已讀回",
  deviated: "與核准內容不同", unknown: "結果未知，待補核對", stale: "相關設定已變，需要重審",
};
const setLabels: Record<ChangeSet["status"], string> = { draft: "待核准", approved: "已核准，逐項處理", rejected: "已拒絕", deferred: "已暫緩", superseded: "已有修訂清單，保留歷史" };
function Values({ value }: { value: SettingValues }) {
  const labels: Record<keyof SettingValues, string> = { title: "標題", body: "內文", titles: "標題（多則）", bodies: "內文（多則）", daily_amount: "每日預算", status: "投放狀態" };
  const fields = Object.entries(value).filter(([key]) => key in labels);
  if (!fields.length) return <p className="text-sm text-muted-foreground">尚未取得可核對設定</p>;
  return <dl className="space-y-2 text-sm">{fields.map(([key, val]) => <div key={key}><dt className="text-xs text-muted-foreground">{labels[key as keyof SettingValues]}</dt><dd className="whitespace-pre-wrap break-words">{key === "status" ? ({ ACTIVE: "啟用", PAUSED: "暫停", ARCHIVED: "已封存", DELETED: "已刪除" }[String(val)] ?? "尚待確認") : String(val ?? "未知")}</dd></div>)}</dl>;
}
export function ChangeSetView({ set, busy, onApprove, onDecision, onItem, onReconsider }: {
  set: ChangeSet; busy: boolean; onApprove: () => void;
  onDecision: (value: { decision: "rejected" | "deferred"; reason: string; revisit_at?: string }) => void;
  onItem: (item: ChangeItem, action: "report" | "check") => void; onReconsider: () => void;
}) {
  const [decision, setDecision] = useState<"rejected" | "deferred" | null>(null);
  const [reason, setReason] = useState("");
  const [revisit, setRevisit] = useState("");
  const confirmed = set.items.filter(item => item.verification_state === "confirmed").length;
  const approved = set.status === "approved";
  const separateHandoff = set.items.some(item => item.kind === "launch" || item.kind === "new_ad");
  const stale = set.items.some(item => ["stale", "deviated"].includes(item.verification_state));
  const unexecuted = approved && set.items.some(item => item.verification_state === "pending");
  return <section className="surface" aria-label="本次變更清單">
    <div className="surface-header flex-wrap gap-3"><div><h2>{set.title}</h2><p className="mt-1 text-xs text-muted-foreground">{set.month} · {approved ? `${confirmed} / ${set.items.length} 項設定已核對` : `共 ${set.items.length} 項變更`}</p></div><Badge variant="secondary">{setLabels[set.status]}</Badge></div>
    <div className="surface-body space-y-4">
      {approved && <p className="text-sm">請依清單到平台手動完成變更，再回來逐項核對。核准與自行回報都不會修改平台。</p>}
      {set.items.map((item, index) => {
        const needsReview = ["stale", "deviated"].includes(item.verification_state);
        const current = item.evidence_json.observed;
        return <article key={item.id} className={`rounded-lg border p-4 space-y-3 ${needsReview ? "border-destructive/30 bg-destructive/5" : "border-border"}`}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="flex items-start gap-2">{item.verification_state === "confirmed" ? <CheckCircle2 className="mt-0.5 size-5 text-success" /> : needsReview ? <AlertTriangle className="mt-0.5 size-5 text-destructive" /> : <Clock className="mt-0.5 size-5 text-warning" />}<div><h3 className="font-medium text-sm">{index + 1}. {targetLabel(item.target)}</h3><p className="text-xs text-muted-foreground">{item.kind === "new_ad" ? "新增另一則廣告，保留原廣告" : item.kind === "launch" ? "首次投放人工交接" : kindLabel[item.kind]}</p></div></div>
            {approved && <Badge variant="outline" className={needsReview ? "text-destructive" : item.verification_state === "confirmed" ? "text-success" : "text-warning"}>{verificationLabels[item.verification_state]}</Badge>}
          </div>
          <p className="text-sm text-muted-foreground">{item.reason}</p>
          {item.kind === "budget" && item.before.daily_amount !== undefined && item.after.daily_amount !== undefined && item.after.daily_amount < item.before.daily_amount && item.verification_state !== "confirmed" && <p className="text-sm text-warning">降額尚未核對，不會先釋放額度。目前 {item.before.daily_amount.toLocaleString()} → 目標 {item.after.daily_amount.toLocaleString()}。</p>}
          <Disclosure label={needsReview ? "查看差異與重審原因" : "查看變更內容與操作對象"} defaultOpen={!approved && index === 0 || needsReview}>
            <div className="space-y-3">
              <div className="grid gap-3 xl:grid-cols-2"><div className="rounded-md bg-muted p-3"><h4 className="mb-2 text-sm font-medium">{needsReview ? "原核准內容" : "變更前"}</h4>{item.kind === "new_ad" ? <p className="text-sm">原廣告與投放組預算保持不變。</p> : <Values value={needsReview ? item.after : item.before} />}</div><div className="rounded-md bg-accent/60 p-3"><h4 className="mb-2 text-sm font-medium">{needsReview ? "平台目前" : "希望調整為"}</h4>{item.kind === "new_ad" ? <div className="space-y-2 text-sm"><p>{item.handoff_snapshot?.filename} · 素材版本 {item.handoff_snapshot?.revision}</p><p>沿用現有父層預算，不另產生可花額度。</p><Values value={{ title: item.handoff_snapshot?.copy.headline, body: item.handoff_snapshot?.copy.body }} /></div> : <Values value={needsReview ? (current && typeof current === "object" ? current as SettingValues : {}) : item.after} />}</div></div>
              {item.kind === "copy" && <p className="flex items-start gap-2 text-sm text-muted-foreground"><Info className="size-4 shrink-0" />只修改原廣告文案，圖片保持不變。文案相符也不代表圖片等價已證實。</p>}
              <p className="text-xs text-muted-foreground">{item.target.platform ?? "平台待指定"} · 帳戶 {item.target.source_account ?? "待對應"} · 平台識別 {item.target.native_id ?? "尚未建立對應"}</p>
              {item.stale_reason && <p className="text-sm text-destructive">{item.stale_reason}</p>}
              {typeof item.evidence_json.message === "string" && <p className="text-sm">{item.evidence_json.message}</p>}
              {item.reported_at && <p className="text-xs text-muted-foreground">使用者回報：{new Date(item.reported_at).toLocaleString("zh-TW")}</p>}
              {item.first_observed_at && <p className="text-xs text-muted-foreground">首次觀測：{new Date(item.first_observed_at).toLocaleString("zh-TW")}；平台實際生效時間仍需其他證據。</p>}
            </div>
          </Disclosure>
          {approved && item.kind !== "new_ad" && item.kind !== "launch" && <>
            {item.verification_state === "confirmed" && <p className="text-xs text-muted-foreground">設定讀回與核准內容相符；實際投遞與成效是否足夠需另行觀察。</p>}
            <div className="flex flex-wrap gap-2">
              {!needsReview && item.verification_state !== "confirmed" && item.verification_state !== "reported" && <Button size="sm" variant="outline" disabled={busy} onClick={() => onItem(item, "report")}>我已手動完成這一項</Button>}
              {!needsReview && <Button size="sm" variant={item.verification_state === "confirmed" ? "outline" : "default"} disabled={busy} onClick={() => onItem(item, "check")}>{busy ? "處理中…" : item.verification_state === "confirmed" ? "重新核對這一項" : "讀回核對這一項"}</Button>}
            </div>
          </>}
        </article>;
      })}
      {!separateHandoff && stale && <div className="rounded-md bg-warning/10 p-3 space-y-2 text-sm"><p>只有相關設定已改變的項目需要重審；其他項目保留自己的結果。一般資料同步不要求重新核准。</p>{set.can_revise !== true && <p>原清單仍有操作尚未核對，或證據已過期。請先核對其他項目，再重新讀取清單。</p>}<Button variant="outline" disabled={busy || set.can_revise !== true} onClick={onReconsider}>依目前設定另建清單</Button></div>}
      {!separateHandoff && unexecuted && !stale && <div className="rounded-md bg-muted p-3 space-y-2 text-sm"><p>若想調整尚未執行的項目，請先逐項讀回，確認平台仍是變更前的設定。已完成項目會保留，不會再次列入。</p><Button variant="outline" disabled={busy || set.can_revise !== true} onClick={onReconsider}>修改尚未執行項目</Button></div>}
      {separateHandoff && <div className="rounded-md bg-accent p-3 text-sm space-y-2"><p>新增物件須在人工交接區逐項核對。原廣告是否暫停另列一項；沒有確認的降額不會釋放額度。</p>{approved ? <a className="text-primary" href="#manual-handoff">前往平台對應核對</a> : <Link className="text-primary" to="?tab=assets">回到素材與計畫檢視</Link>}</div>}
      {(set.status === "draft" || set.status === "deferred") && <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4"><p className="max-w-prose text-xs text-muted-foreground">核准只代表同意這份清單，之後仍由你到平台手動操作。</p><div className="flex flex-wrap gap-2"><Button disabled={busy} onClick={onApprove}>{busy ? "處理中…" : "核准這份變更清單"}</Button>{!separateHandoff && <Button variant="outline" disabled={busy} onClick={onReconsider}>修改清單</Button>}<Button variant="outline" disabled={busy} onClick={() => setDecision("rejected")}>拒絕</Button><Button variant="outline" disabled={busy} onClick={() => setDecision("deferred")}>暫緩</Button></div></div>}
      {decision && <form className="rounded-md border border-border p-4 space-y-3" onSubmit={e => { e.preventDefault(); onDecision({ decision, reason, ...(decision === "deferred" ? { revisit_at: new Date(revisit).toISOString() } : {}) }); }}>
        <label className="block text-sm">{decision === "deferred" ? "暫緩原因與待補條件" : "拒絕原因"}<Textarea aria-label="決定原因" value={reason} onChange={e => setReason(e.target.value)} required disabled={busy} /></label>
        {decision === "deferred" && <label className="block text-sm">重看時間<Input aria-label="重看時間" type="datetime-local" value={revisit} onChange={e => setRevisit(e.target.value)} required disabled={busy} /></label>}
        <p className="text-xs text-muted-foreground">此決定不會停止平台投放，也不代表清單中的操作已完成。</p>
        <div className="flex gap-2"><Button type="submit" disabled={busy || !reason.trim() || decision === "deferred" && !revisit}>保存決定</Button><Button type="button" variant="outline" disabled={busy} onClick={() => setDecision(null)}>取消</Button></div>
      </form>}
      {(set.status === "rejected" || set.status === "deferred") && <div className="rounded-md bg-muted p-3 text-sm space-y-1"><p>{set.reason}</p>{set.revisit_at && <p>重看時間：{new Date(set.revisit_at).toLocaleString("zh-TW")}</p>}<p className="text-muted-foreground">本次決定不會停止平台廣告。活動花費與重要期限仍需持續查看。</p></div>}
      {!separateHandoff && set.status === "rejected" && <Button variant="outline" disabled={busy} onClick={onReconsider}>依目前設定另建清單</Button>}
      {approved && <p className="flex items-start gap-2 rounded-md bg-background p-3 text-xs text-muted-foreground"><Info className="size-4 shrink-0" />本次檢討是否完成、執行清單是否完成、活動是否持續投放，是三件不同的事。</p>}
    </div>
  </section>;
}
