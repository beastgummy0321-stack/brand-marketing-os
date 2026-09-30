import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { saveConversionGoal } from "@/lib/intakeApi";
import { fetchOnboardingTools, type Connector, type OnboardingTools } from "@/lib/intakeOnboardingApi";
import { cn } from "@/lib/utils";
import { BarNext, OnboardingBar, OnboardingStepHead, type BarBack, type StepNav } from "../OnboardingStepHead";
import { MetaConnectPanel } from "./MetaConnectPanel";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; tools: OnboardingTools };

/** Accepted deviation from the prototype's 「之後在「設定 → 接工具」隨時再接」: the places to connect later are this
 * step (re-entry through 品牌資料) and 投放中心's 資料連線. */
const HINT = "之後回到「品牌資料」或投放中心的資料連線再接";

/** Brand onboarding #/b6 接上工具 (prototype `R.b6` of `.harness/scratch/prototype/f41-onboarding/index.html`): the
 * connector registry (`GET …/onboarding/tools`) as one card per group, each row saying what the system can read
 * once connected; only live connectors can be connected, the rest are honest seats (「即將開放」). Meta's 接上／換一個
 * opens the existing token → account flow inline (`MetaConnectPanel`); a connector with an in-app page (the orders
 * file) links there. Then 成效目標, saved on change (`POST …/conversion-goal`). Skipping every connector is allowed. */
export function ToolsStep({ brandId, nav, back, onNext }: { brandId: string; nav: StepNav; back?: BarBack; onNext: () => void }) {
  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  const [metaOpen, setMetaOpen] = useState(false);
  const [savingGoal, setSavingGoal] = useState(false);
  const [goalError, setGoalError] = useState<string | null>(null);

  function reload(quiet = false) {
    if (!quiet) setLoad({ status: "loading" });
    fetchOnboardingTools(brandId)
      .then((tools) => setLoad({ status: "ready", tools }))
      .catch((err: unknown) => {
        if (!quiet) setLoad({ status: "error", message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。" });
      });
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => reload(), [brandId]);

  async function selectGoal(goal: string) {
    if (load.status !== "ready" || goal === load.tools.conversion_goal) return;
    setSavingGoal(true);
    setGoalError(null);
    try {
      await saveConversionGoal(brandId, goal);
      setLoad({ status: "ready", tools: { ...load.tools, conversion_goal: goal } });
    } catch (err) {
      setGoalError(err instanceof Error ? err.message : "儲存失敗，請稍後再試。");
    } finally {
      setSavingGoal(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <OnboardingStepHead {...nav} title="接上工具" purpose="接越多，系統看得越清楚；現在只要 Meta 就能開始，其他之後再接" />
      {load.status === "loading" && <p className="rounded-xl border border-border bg-card px-[22px] py-5 text-sm text-muted-foreground">讀取中…</p>}
      {load.status === "error" && (
        <div className="flex flex-col items-start gap-2 rounded-xl border border-border bg-card px-[22px] py-5">
          <p role="alert" className="text-sm text-danger">{load.message}</p>
          <Button type="button" variant="link" className="h-auto p-0 text-[13px]" onClick={() => reload()}>重新載入</Button>
        </div>
      )}
      {load.status === "ready" && (
        <>
          {groupConnectors(load.tools.connectors).map(([group, rows]) => (
            <section key={group} data-slot="connector-group" className="rounded-xl border border-border bg-card px-[22px] py-5">
              <h2 className="mb-3.5 text-base font-semibold">{group}</h2>
              {rows.map((c) => (
                <ConnectorRow
                  key={c.key}
                  connector={c}
                  metaOpen={metaOpen}
                  onToggleMeta={() => setMetaOpen((open) => !open)}
                  panel={c.key === "meta" && metaOpen ? <MetaConnectPanel brandId={brandId} onBound={() => reload(true)} /> : null}
                />
              ))}
            </section>
          ))}
          <section className="rounded-xl border border-border bg-card px-[22px] py-5">
            <div className="grid grid-cols-[170px_minmax(0,1fr)] items-start gap-x-5 gap-y-2.5 max-sm:grid-cols-1">
              <div>
                <b className="block text-sm font-semibold">成效目標</b>
                <span className="mt-0.5 block text-xs text-muted-foreground">廣告要帶來什麼</span>
              </div>
              <div className="min-w-0">
                <GoalSegmented
                  options={load.tools.conversion_goal_options}
                  value={load.tools.conversion_goal}
                  disabled={savingGoal}
                  onChange={(goal) => void selectGoal(goal)}
                />
                {goalError && <p role="alert" className="mt-2 text-xs text-danger">{goalError}</p>}
              </div>
            </div>
          </section>
        </>
      )}
      <OnboardingBar back={back} hint={HINT}>
        <BarNext label="完成品牌建檔" onClick={onNext} />
      </OnboardingBar>
    </div>
  );
}

/** Registry order is kept: groups in order of first appearance, rows in registry order within a group. */
function groupConnectors(connectors: Connector[]): [string, Connector[]][] {
  const groups = new Map<string, Connector[]>();
  for (const c of connectors) groups.set(c.group, [...(groups.get(c.group) ?? []), c]);
  return [...groups.entries()];
}

/** Prototype `.conn`: icon tile, name, 「接上後系統能讀：…」, the connected note, and the row's action. */
function ConnectorRow({ connector: c, metaOpen, onToggleMeta, panel }: {
  connector: Connector;
  metaOpen: boolean;
  onToggleMeta: () => void;
  panel: ReactNode;
}) {
  const connected = c.state === "connected";
  return (
    <div data-slot="connector" data-state={c.state} className="border-t border-border py-3 last:pb-0">
      <div className="grid grid-cols-[40px_minmax(0,1fr)_auto] items-center gap-3">
        <span
          aria-hidden="true"
          className={cn(
            "grid size-10 place-items-center rounded-[10px] text-[13px] font-bold",
            connected ? "bg-accent text-accent-foreground" : "bg-muted text-muted-foreground",
          )}
        >
          {c.icon}
        </span>
        <div className="min-w-0">
          <b className="font-semibold">{c.label}</b>
          <div className="text-[11.5px] text-muted-foreground">接上後系統能讀：{c.reads}</div>
          {connected && c.note && <div className="mt-0.5 text-[11.5px] text-success">✓ {c.note}</div>}
        </div>
        <ConnectorAction connector={c} metaOpen={metaOpen} onToggleMeta={onToggleMeta} />
      </div>
      {panel && <div className="mt-3 ml-[52px] rounded-lg border border-border bg-background p-3">{panel}</div>}
    </div>
  );
}

function ConnectorAction({ connector: c, metaOpen, onToggleMeta }: { connector: Connector; metaOpen: boolean; onToggleMeta: () => void }) {
  if (c.state === "seat") {
    return <span className="rounded-full bg-muted px-2.5 py-0.5 text-xs font-medium whitespace-nowrap text-muted-foreground">{c.note || "即將開放"}</span>;
  }
  if (c.key === "meta") {
    return c.state === "connected" ? (
      <Button type="button" variant="link" className="h-auto p-0 text-[13px]" aria-expanded={metaOpen} onClick={onToggleMeta}>
        {metaOpen ? "收起" : "換一個"}
      </Button>
    ) : (
      <Button type="button" variant="outline" size="sm" aria-expanded={metaOpen} onClick={onToggleMeta}>
        {metaOpen ? "收起" : "接上"}
      </Button>
    );
  }
  if (c.link) {
    return (
      <Button asChild variant={c.state === "connected" ? "link" : "outline"} size="sm">
        <Link to={c.link}>{c.state === "connected" ? "換一個" : "接上"}</Link>
      </Button>
    );
  }
  return null;
}

/** Prototype `.seg`: one-of segmented control, radio keyboard pattern (the picked option is the tab stop). No goal saved
 * yet → nothing is picked; the first option is then the tab stop. */
function GoalSegmented({ options, value, disabled, onChange }: {
  options: { key: string; label: string }[];
  value: string | null;
  disabled: boolean;
  onChange: (key: string) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const stop = options.some((o) => o.key === value) ? value : options[0]?.key;
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const keys = ["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp", "Home", "End"];
    if (disabled || !keys.includes(e.key) || !ref.current) return;
    e.preventDefault();
    const radios = Array.from(ref.current.querySelectorAll<HTMLButtonElement>("[role=radio]"));
    const at = radios.indexOf(document.activeElement as HTMLButtonElement);
    const next = e.key === "Home" ? 0
      : e.key === "End" ? radios.length - 1
      : e.key === "ArrowRight" || e.key === "ArrowDown" ? (at + 1) % radios.length
      : (at - 1 + radios.length) % radios.length;
    radios[next].focus();
    onChange(options[next].key);
  };
  return (
    <div
      ref={ref}
      role="radiogroup"
      aria-label="成效目標"
      onKeyDown={onKeyDown}
      className="flex overflow-hidden rounded-lg border border-border"
    >
      {options.map((o, i) => {
        const on = o.key === value;
        return (
          <button
            key={o.key}
            type="button"
            role="radio"
            aria-checked={on}
            tabIndex={o.key === stop ? 0 : -1}
            disabled={disabled}
            onClick={() => onChange(o.key)}
            className={cn(
              "px-3 py-[5px] text-[12.5px] font-medium disabled:cursor-default",
              i > 0 && "border-l border-border",
              on ? "bg-primary text-primary-foreground" : "bg-card hover:text-primary",
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
