import { GRADE_FILL } from "./Chip";
import { Term } from "./Term";
import { useAdsRules, watchTenths } from "./rules";

/** v10 `moneyRule()`: one line naming the two rulers — 有賺／在虧 against break-even, grades against the cap.
 * `data-slot="money-rule"`. */
export function MoneyRule({ breakEven }: { breakEven?: number | null }) {
  return (
    <div data-slot="money-rule" className="mt-1 text-[11.5px] text-muted-foreground">
      <Term k="money">有賺／在虧</Term>：跟<Term k="break_even" value={breakEven}>打平線</Term>比；分級：跟你的<Term k="cap">上限</Term>比
    </div>
  );
}

const ROWS = ["on_target", "watch", "over", "wasted"] as const;

/** v10 `gradeRules()`: the compact grade legend (one swatch + term per grade), then the money rule. Show it once
 * per screen — the prototype prints it only on its first use. Words and the 偏貴 band are the served rules (F48
 * Contract R-API); until they load the legend waits (nothing to print without them) and the money rule shows alone.
 * `data-slot="grade-rules"`. */
export function GradeRules({ money = true, breakEven }: { money?: boolean; breakEven?: number | null }) {
  const rules = useAdsRules();
  const tenths = rules ? watchTenths(rules) : null;
  const rest = { watch: `＝超過上限不到 ${tenths} 成`, over: `＝超過 ${tenths} 成以上`, wasted: "＝花了錢一筆都沒賣" } as const;
  return (
    <div data-slot="grade-rules" className="mt-2">
      {rules && (
        <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-muted-foreground">
          {ROWS.map((grade) => (
            <span key={grade}>
              <i aria-hidden="true" className={`mr-[5px] inline-block size-2 rounded-[2px] ${GRADE_FILL[grade]}`} />
              <Term k={grade}>{rules.labels.grade[grade]}</Term>
              {grade === "on_target" ? <>＝每筆沒超過<Term k="cap">上限</Term></> : rest[grade]}
            </span>
          ))}
        </div>
      )}
      {money && <MoneyRule breakEven={breakEven} />}
    </div>
  );
}
