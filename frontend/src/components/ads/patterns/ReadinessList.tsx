import { Link } from "react-router-dom";
import type { LaunchReadiness, ReadinessState } from "@/lib/adsLaunchApi";

const STATE_BORDER: Record<ReadinessState, string> = {
  green: "border-success/30 bg-success/5",
  yellow: "border-warning/30 bg-warning/5",
  red: "border-danger/30 bg-danger/5",
};

const STATE_BADGE: Record<ReadinessState, string> = {
  green: "bg-success",
  yellow: "bg-warning",
  red: "bg-danger",
};

const STATE_TEXT: Record<ReadinessState, string> = {
  green: "text-success",
  yellow: "text-warning",
  red: "text-danger",
};

/** 可投放檢查表（F05-I10）：三色三列，句子與顏色都來自 `app/ads/readiness.py`，
 * 這支只負責照 state 上色，不重拼句子、不重判斷。 */
export function ReadinessList({ readiness }: { readiness: LaunchReadiness }) {
  return (
    <div className="flex flex-col gap-3">
      {readiness.items.map((item) => (
        <div
          key={item.key}
          className={`flex items-start gap-3 rounded-md border p-4 ${STATE_BORDER[item.state]}`}
        >
          <span
            className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs font-bold text-white ${STATE_BADGE[item.state]}`}
          >
            {item.state === "green" ? "✓" : "!"}
          </span>
          <div className="flex flex-col gap-0.5">
            <p className="font-medium text-foreground">{item.label}</p>
            <p className={`text-sm ${STATE_TEXT[item.state]}`}>{item.reason}</p>
            {item.state !== "green" && (
              <Link to={item.fix_href} className="w-fit text-sm font-medium text-primary hover:underline">
                {item.fix_label}
              </Link>
            )}
          </div>
        </div>
      ))}
      {readiness.notes.length > 0 && (
        <div className="flex flex-col gap-1">
          {readiness.notes.map((note) => (
            <p key={note.key} className="text-sm text-muted-foreground">
              {note.text}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}
