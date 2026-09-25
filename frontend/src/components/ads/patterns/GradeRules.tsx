import { GRADE_FILL } from "./Chip";
import { Term } from "./Term";

/** v10 `moneyRule()`: one line naming the two rulers — 有賺／在虧 against break-even, grades against the cap.
 * `data-slot="money-rule"`. */
export function MoneyRule({ breakEven }: { breakEven?: number | null }) {
  return (
    <div data-slot="money-rule" className="mt-1 text-[11.5px] text-muted-foreground">
      <Term k="money">有賺／在虧</Term>：跟<Term k="break_even" value={breakEven}>打平線</Term>比；分級：跟你的<Term k="cap">上限</Term>比
    </div>
  );
}

const ROWS = [
  { grade: "on_target", key: "on_target", word: "划算" },
  { grade: "watch", key: "watch", word: "偏貴" },
  { grade: "over", key: "over", word: "太貴" },
  { grade: "wasted", key: "wasted", word: "沒賣出" },
] as const;

/** v10 `gradeRules()`: the compact grade legend (one swatch + term per grade), then the money rule. Show it once
 * per screen — the prototype prints it only on its first use. `data-slot="grade-rules"`. */
export function GradeRules({ money = true, breakEven }: { money?: boolean; breakEven?: number | null }) {
  const rest = { watch: "＝超過上限不到 2 成", over: "＝超過 2 成以上", wasted: "＝花了錢一筆都沒賣" } as const;
  return (
    <div data-slot="grade-rules" className="mt-2">
      <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-muted-foreground">
        {ROWS.map((row) => (
          <span key={row.grade}>
            <i aria-hidden="true" className={`mr-[5px] inline-block size-2 rounded-[2px] ${GRADE_FILL[row.grade]}`} />
            <Term k={row.key}>{row.word}</Term>
            {row.grade === "on_target" ? <>＝每筆沒超過<Term k="cap">上限</Term></> : rest[row.grade]}
          </span>
        ))}
      </div>
      {money && <MoneyRule breakEven={breakEven} />}
    </div>
  );
}
