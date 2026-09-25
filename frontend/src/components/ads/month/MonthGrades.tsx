import type { MonthGrades as Grades, PeriodGradeBucket } from "@/lib/adsMonthApi";
import type { TriageGrade } from "@/lib/adsTriageApi";
import { Chip, GradeBar, ThumbTiles, type ChipTone, type GradeBarBucket } from "../patterns";
import { countWord, mmdd, money } from "./monthCsv";

/** F29-I15: the month's spend split by the one cap ruler (prototype v10 `month()` split card + `bucket()` cards;
 * Feature F29 Contract C `grades`, the same rows a settle of this month reads). 有效 counts 划算 only. */

const THIN = "剛開始、數字還不夠";
// A real brand often has 20+ ads in one bucket; the rest fold into ThumbTiles' 「＋N 則」.
const TILE_LIMIT = 12;

/** One break-even for the rules line only when every graded ad shares it; otherwise the term stays without one. */
function sharedBreakEven(grades: Grades): number | null {
  const values = new Set(grades.rows.map((row) => row.break_even));
  return values.size === 1 ? [...values][0] : null;
}

/** 「中秋限定活動缺 09/17、09/18 兩天資料，這兩天不計；其他天照常算」, one line per campaign with missing days. */
export function MissingNote({ grades }: { grades: Grades }) {
  if (grades.missing.length === 0) return null;
  return (
    <div className="mt-2 flex flex-col gap-0.5 text-xs text-muted-foreground" data-part="missing-days">
      {grades.missing.map((m) => {
        const days = m.missing_days.map(mmdd);
        const shown = days.length > 6 ? `${days.slice(0, 6).join("、")} 等` : days.join("、");
        const n = countWord(days.length);
        return <span key={m.campaign_id}>{m.name}缺 {shown} {n}天資料，這{n}天不計；其他天照常算</span>;
      })}
    </div>
  );
}

/** Prototype split card: 「9 月已花 22,000 元，分到這幾格」 + the grade bar with amounts + the grade rules. An unknown
 * total (two currencies, or a day's spend unknown) never prints as 0. */
export function GradeSplit({ month, grades }: { month: number; grades: Grades }) {
  const buckets: GradeBarBucket[] = grades.buckets.map((b) => ({ grade: b.grade, amount: b.amount, count: b.count }));
  const title = grades.spent === null ? `${month} 月的花費分到這幾格` : `${month} 月已花 ${money(grades.spent)}，分到這幾格`;
  return (
    <section aria-label="花費分到哪幾格" className="surface px-[22px] py-5">
      <div className="mb-3.5 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-[15px] font-semibold">{title}</h2>
        <span className="text-[13px] text-muted-foreground">
          {grades.spent === null && "總額未知（幣別不同或有天數缺花費）・"}每則對照所屬活動的上限
        </span>
      </div>
      {grades.rows.length === 0
        ? <p className="text-sm text-muted-foreground">這個月還沒有花到錢的廣告。</p>
        : <GradeBar buckets={buckets} withMoney breakEven={sharedBreakEven(grades)} />}
      <MissingNote grades={grades} />
    </section>
  );
}

interface BucketSpec { title: string; tone: ChipTone; grades: TriageGrade[]; caption: string }

const BUCKETS: BucketSpec[] = [
  { title: "有效（只算划算）", tone: "ok", grades: ["on_target"], caption: "每筆在上限內" },
  { title: "偏貴", tone: "warn", grades: ["watch"], caption: "超過上限 2 成內" },
  { title: "太貴・沒賣出", tone: "bad", grades: ["over", "wasted"], caption: "超過 2 成，或花了錢沒賣出" },
  { title: THIN, tone: "neutral", grades: ["insufficient"], caption: "還沒花到上限 × 3" },
];

function merge(buckets: PeriodGradeBucket[], grades: TriageGrade[]) {
  const own = buckets.filter((b) => grades.includes(b.grade));
  return {
    count: own.reduce((s, b) => s + b.count, 0),
    amount: own.some((b) => b.amount === null) ? null : own.reduce((s, b) => s + (b.amount as number), 0),
    thumbs: own.flatMap((b) => b.ads.map((ad) => ad.thumbnail_url)),
  };
}

/** The four bucket cards (prototype `bucket()`); `withAmounts` adds 「・花 X 元」 to each caption. */
export function GradeBuckets({ grades, withAmounts }: { grades: Grades; withAmounts: boolean }) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {BUCKETS.map((spec) => {
        const b = merge(grades.buckets, spec.grades);
        const spend = b.amount === null ? "花費未知" : `花 ${money(b.amount)}`;
        return (
          <section key={spec.title} aria-label={spec.title} data-bucket={spec.grades.join(",")} className="surface px-[22px] py-5">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-[15px] font-semibold">{spec.title}</h2>
              <Chip tone={spec.tone}>{b.count} 則</Chip>
            </div>
            <div className="text-xs text-muted-foreground">{spec.caption}{withAmounts && `・${spend}`}</div>
            {b.count > 0
              ? <div className="mt-1"><ThumbTiles items={b.thumbs} size={44} max={TILE_LIMIT} /></div>
              : <p className="mt-3 text-sm text-muted-foreground">0 則</p>}
          </section>
        );
      })}
    </div>
  );
}
