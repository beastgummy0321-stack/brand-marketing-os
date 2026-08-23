import { useEffect, useState, type ComponentType, type ReactNode } from "react";
import {
  Check,
  ChevronDown,
  ChevronLeft,
  Clapperboard,
  FileText,
  ImageIcon,
  Info,
  LoaderCircle,
  Package,
  RefreshCw,
  TriangleAlert,
  Video,
  Zap,
} from "lucide-react";
import { cn, PRESS_FEEDBACK } from "@/lib/utils";
import {
  fetchQuickGenerateProducts,
  parseVideoScript,
  quickGenerate,
  SINGLE_IMAGE_CHAR_BUDGETS,
  VIDEO_CHAR_BUDGETS,
  type QuickGenerateComponent,
  type QuickGenerateProduct,
  type QuickGenerateResult,
  type QuickGenerateScope,
} from "@/lib/workbenchApi";
import { ComplianceBadges } from "./shared/ComplianceBadges";
import { CopyIconButton } from "./shared/CopyIconButton";
import { FoldedText } from "./shared/FoldedText";

/** 四選一入口卡的顯示表（契約 G12.1）：`key` 是後端 `QUICK_GENERATE_SCOPES` 的鍵，欄位
 * 數量抄自 app/creative/format_specs.py FORMAT_SPECS（image_prompt 10／body 5／
 * hook_pool 10／script 3，查證日 2026-08-11）——快速生成沒有行銷目標，數量直接讀規格表
 * 原始定義（後端 `build_quick_generate_plan()` 同一個判準），不隨目標變動。`bodyBudget`
 * 取既有抄錄表，不另抄一個數字。 */
const SCOPE_CARDS: {
  key: QuickGenerateScope;
  title: string;
  Icon: ComponentType<{ className?: string }>;
  chips: { Icon: ComponentType<{ className?: string }>; label: string; n: number }[];
  sections: ("prompts" | "hooks" | "scripts" | "bodies")[];
  bodyBudget: number;
}[] = [
  {
    key: "post",
    title: "完整貼文",
    Icon: FileText,
    chips: [
      { Icon: ImageIcon, label: "提示詞", n: 10 },
      { Icon: FileText, label: "文案", n: 5 },
    ],
    sections: ["prompts", "bodies"],
    bodyBudget: SINGLE_IMAGE_CHAR_BUDGETS.body,
  },
  {
    key: "video",
    title: "完整影片",
    Icon: Video,
    chips: [
      { Icon: Zap, label: "Hook", n: 10 },
      { Icon: Clapperboard, label: "腳本", n: 3 },
      { Icon: FileText, label: "文案", n: 5 },
    ],
    sections: ["hooks", "scripts", "bodies"],
    bodyBudget: VIDEO_CHAR_BUDGETS.body,
  },
  {
    key: "image",
    title: "單張圖片",
    Icon: ImageIcon,
    chips: [{ Icon: ImageIcon, label: "提示詞", n: 10 }],
    sections: ["prompts"],
    bodyBudget: SINGLE_IMAGE_CHAR_BUDGETS.body,
  },
  {
    key: "script",
    title: "單則腳本",
    Icon: Clapperboard,
    chips: [
      { Icon: Zap, label: "Hook", n: 10 },
      { Icon: Clapperboard, label: "腳本", n: 3 },
    ],
    sections: ["hooks", "scripts"],
    bodyBudget: VIDEO_CHAR_BUDGETS.body,
  },
];

/** 多則整組複製的分隔字串：沿用側板整組複製既有先例（ThemePanel.tsx 圖片提示詞整組複製，
 * 票 17），不另訂一種分隔法。 */
const COPY_ALL_SEPARATOR = "\n\n----------\n\n";

type RunState =
  | { status: "idle" }
  | { status: "running" }
  | { status: "done"; result: QuickGenerateResult }
  | { status: "failed"; message: string };

/** 快速生成（畫面1 下半，契約 G12.0–G12.10）：免排程免切角，選類型＋可選產品＋一句話重點
 * 直接生成，**不落地**——端點回應即棄，離開這頁就沒了（G12.9 的提示不是客套話）。
 *
 * 四態：空（選好類型後的表單）／進行中／正常（結果）／失敗，由 `run` 這個判別聯集決定，
 * 沒有選類型時顯示四張入口卡。結果不排序、不比較、沒有採用動作，只有複製（G12.5）。 */
export function QuickGenerate({ brandId }: { brandId: string }) {
  const [scope, setScope] = useState<QuickGenerateScope | null>(null);
  // null＝還在讀，[]＝這個品牌真的沒有產品。兩者分開才畫得出空狀態，
  // 否則「讀取中」跟「沒有產品」長得一樣，看起來就像壞了。
  const [products, setProducts] = useState<QuickGenerateProduct[] | null>(null);
  const [productsError, setProductsError] = useState<string | null>(null);
  const [productId, setProductId] = useState<string | null>(null);
  const [topic, setTopic] = useState("");
  const [run, setRun] = useState<RunState>({ status: "idle" });

  useEffect(() => {
    let cancelled = false;
    fetchQuickGenerateProducts(brandId)
      .then((list) => {
        if (!cancelled) setProducts(list);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setProductsError(err instanceof Error ? err.message : "產品清單讀取失敗");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [brandId]);

  const card = SCOPE_CARDS.find((c) => c.key === scope);

  /** 生成／重生同一顆進入點（G12.7）：重生就是拿同一組 scope／product／topic 再打一次，
   * 不另做一條路徑。進行中時「換一種」會被 disabled，所以不會有舊請求回來蓋掉新類型結果。 */
  function handleGenerate() {
    if (!scope || !topic.trim()) return;
    setRun({ status: "running" });
    quickGenerate(brandId, scope, topic.trim(), productId)
      .then((result) => setRun({ status: "done", result }))
      .catch((err: unknown) => {
        setRun({
          status: "failed",
          message: err instanceof Error ? err.message : "生成失敗，請稍後再試。",
        });
      });
  }

  return (
    <section className="flex flex-col gap-4 rounded-lg border border-border bg-card p-5 shadow-[var(--shadow-card)]">
      <div className="flex items-center gap-2">
        <h2 className="font-display text-base text-foreground">快速生成</h2>
        <p className="text-xs text-muted-foreground">免排程免切角，打重點即生。</p>
        {card && (
          <button
            type="button"
            onClick={() => {
              setScope(null);
              setRun({ status: "idle" });
            }}
            disabled={run.status === "running"}
            className="ml-auto inline-flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
          >
            <ChevronLeft className="h-3.5 w-3.5" aria-hidden="true" />
            換一種
          </button>
        )}
      </div>

      {!card ? (
        <div className="grid grid-cols-2 gap-3">
          {SCOPE_CARDS.map(({ key, title, Icon, chips }) => (
            <button
              key={key}
              type="button"
              onClick={() => {
                setScope(key);
                setRun({ status: "idle" });
              }}
              className={cn(
                "flex flex-col gap-2 rounded-lg border border-border p-4 text-left transition-colors hover:border-primary",
                PRESS_FEEDBACK,
              )}
            >
              <span className="flex items-center gap-2 text-primary">
                <Icon className="h-5 w-5" aria-hidden="true" />
                <b className="text-sm text-foreground">{title}</b>
              </span>
              <span className="flex gap-3 text-xs text-muted-foreground">
                {/* 原型是「圖示＋數字」不寫欄位名（字愈少愈好）；欄位名走 title 與唯讀
                    文字，滑鼠停留看得到、螢幕閱讀器讀得到，不是只有一個裸數字。 */}
                {chips.map((chip) => (
                  <span key={chip.label} className="flex items-center gap-1" title={chip.label}>
                    <chip.Icon className="h-3.5 w-3.5" aria-hidden="true" />
                    <span className="sr-only">{chip.label}</span>
                    {chip.n}
                  </span>
                ))}
              </span>
            </button>
          ))}
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <div className="flex items-center gap-2 text-primary">
            <card.Icon className="h-4 w-4" aria-hidden="true" />
            <h3 className="text-sm font-semibold text-foreground">{card.title}</h3>
          </div>

          {run.status === "idle" && (
            <>
              <div className="flex flex-col gap-2">
                <span className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
                  <Package className="h-3.5 w-3.5" aria-hidden="true" />
                  套用產品
                </span>
                <div role="radiogroup" aria-label="套用產品" className="flex flex-wrap gap-2">
                  <ProductPill
                    label="不指定"
                    selected={productId === null}
                    onSelect={() => setProductId(null)}
                  />
                  {(products ?? []).map((product) => (
                    <ProductPill
                      key={product.id}
                      label={product.name}
                      selected={productId === product.id}
                      onSelect={() => setProductId(product.id)}
                    />
                  ))}
                </div>
                {productsError && <p className="text-xs text-danger">{productsError}</p>}
                {!productsError && products?.length === 0 && (
                  <p className="text-xs text-muted-foreground">
                    這個品牌還沒登錄產品，這次只用品牌資料生成。
                  </p>
                )}
              </div>

              <div className="flex flex-col gap-2">
                <label
                  htmlFor="quick-generate-topic"
                  className="text-xs font-semibold text-muted-foreground"
                >
                  這次想講的重點
                </label>
                <textarea
                  id="quick-generate-topic"
                  value={topic}
                  onChange={(event) => setTopic(event.target.value)}
                  rows={2}
                  placeholder="開學季新品、加碼贈品、限時 95 折⋯"
                  className="w-full resize-y rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/70"
                />
              </div>

              <div className="flex justify-end">
                <button
                  type="button"
                  onClick={handleGenerate}
                  disabled={!topic.trim()}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50",
                    PRESS_FEEDBACK,
                  )}
                >
                  <Zap className="h-4 w-4" aria-hidden="true" />
                  生成
                </button>
              </div>
            </>
          )}

          {run.status === "running" && <RunningState />}

          {run.status === "failed" && (
            <div className="flex flex-col gap-3">
              <p
                role="alert"
                className="flex items-center gap-2 rounded-md border border-danger/30 bg-danger/10 px-3 py-2.5 text-sm text-danger"
              >
                <TriangleAlert className="h-4 w-4 shrink-0" aria-hidden="true" />
                {run.message}
              </p>
              <div className="flex justify-end">
                <button
                  type="button"
                  onClick={() => setRun({ status: "idle" })}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90",
                    PRESS_FEEDBACK,
                  )}
                >
                  <RefreshCw className="h-4 w-4" aria-hidden="true" />
                  重試
                </button>
              </div>
            </div>
          )}

          {run.status === "done" && (
            <ResultView
              result={run.result}
              sections={card.sections}
              bodyBudget={card.bodyBudget}
              onRegenerate={handleGenerate}
            />
          )}
        </div>
      )}
    </section>
  );
}

/** 進行中（G12.3）：圖示＋單行文字，兩階段——「整理品牌資料」→「生成中」。**沒有第三階段
 * 「存起來」**（不落地定案）。
 *
 * ponytail：階段切換是前端計時器，不是端點回報的真實進度——端點是同步的，回來時已經整包
 * 做完，中途沒有任何可讀的階段欄位（app/ads/routes_quick_generate.py 只回 {result} 或
 * {error}）。天花板：兩段文字的切換時機是估的，不是量到的。升級路徑：端點改成 SSE／
 * WebSocket 分階回報後，把這個計時器換成讀端點回來的階段。 */
function RunningState() {
  const [phase, setPhase] = useState<"context" | "generating">("context");

  useEffect(() => {
    const timer = setTimeout(() => setPhase("generating"), 900);
    return () => clearTimeout(timer);
  }, []);

  return (
    <p
      aria-live="polite"
      className="flex flex-col items-center gap-2 py-8 text-sm font-medium text-secondary"
    >
      <LoaderCircle
        className="h-6 w-6 animate-spin text-primary motion-reduce:animate-none"
        aria-hidden="true"
      />
      {phase === "context" ? "整理品牌資料" : "生成中"}
    </p>
  );
}

function ProductPill({
  label,
  selected,
  onSelect,
}: {
  label: string;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onSelect}
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-3 py-1 text-xs font-medium",
        selected
          ? "border-primary bg-primary/10 text-primary"
          : "border-border text-foreground hover:border-primary",
        PRESS_FEEDBACK,
      )}
    >
      {selected && <Check className="h-3 w-3" aria-hidden="true" />}
      {label}
    </button>
  );
}

/** 正常態（G12.4）：依所選類型顯示對應區塊，各區塊全部列出，不是十選一。5 則文案彼此獨立、
 * 不排序、沒有採用動作（G12.5），只有複製。 */
function ResultView({
  result,
  sections,
  bodyBudget,
  onRegenerate,
}: {
  result: QuickGenerateResult;
  sections: ("prompts" | "hooks" | "scripts" | "bodies")[];
  bodyBudget: number;
  onRegenerate: () => void;
}) {
  const pick = (type: string) => result.components.filter((c) => c.component_type === type);
  const prompts = pick("image_prompt");
  const hooks = pick("hook_pool");
  const scripts = pick("script");
  const bodies = pick("body");

  return (
    <div className="flex flex-col gap-5">
      <p className="flex items-center gap-1.5 text-xs font-medium text-success">
        <Check className="h-3.5 w-3.5" aria-hidden="true" />
        完成
      </p>

      {sections.includes("prompts") && prompts.length > 0 && (
        <SectionShell
          Icon={ImageIcon}
          title="提示詞"
          count={prompts.length}
          /* G12.10 整組複製：只有提示詞區塊有（貼文／單張圖片兩類型），多則以既有分隔字串
             串起來，跟側板整組複製同一種語意與文案。 */
          headerExtra={
            <CopyIconButton
              label="整組複製"
              ariaLabel="整組複製圖片提示詞"
              getText={() => prompts.map((c) => c.content).join(COPY_ALL_SEPARATOR)}
            />
          }
        >
          <div className="grid grid-cols-2 gap-2">
            {prompts.map((component, index) => (
              <PromptRow key={index} index={index} content={component.content} />
            ))}
          </div>
        </SectionShell>
      )}

      {sections.includes("hooks") && hooks.length > 0 && (
        <SectionShell Icon={Zap} title="Hook" count={hooks.length}>
          <div className="flex flex-wrap gap-2">
            {hooks.map((component, index) => (
              <div key={index} className="flex flex-col items-start">
                <CopyIconButton
                  label={component.content}
                  ariaLabel={`複製 Hook：${component.content}`}
                  getText={() => component.content}
                  className="max-w-[18rem] rounded-full [&>span]:min-w-0 [&>span]:truncate"
                />
                <ComplianceBadges hits={component.compliance_hits} />
              </div>
            ))}
          </div>
        </SectionShell>
      )}

      {sections.includes("scripts") && scripts.length > 0 && (
        <SectionShell Icon={Clapperboard} title="腳本" count={scripts.length}>
          <div className="flex flex-col gap-2">
            {scripts.map((component, index) => (
              <ScriptCard key={index} index={index} component={component} />
            ))}
          </div>
        </SectionShell>
      )}

      {sections.includes("bodies") && bodies.length > 0 && (
        <SectionShell Icon={FileText} title="文案" count={bodies.length}>
          <div className="grid grid-cols-2 gap-2">
            {bodies.map((component, index) => (
              <div key={index} className="rounded-md border border-border px-3 py-2">
                <FoldedText content={component.content} charBudget={bodyBudget} />
                <ComplianceBadges hits={component.compliance_hits} />
                <div className="mt-1 flex justify-end">
                  <CopyIconButton ariaLabel="複製這則文案" getText={() => component.content} />
                </div>
              </div>
            ))}
          </div>
        </SectionShell>
      )}

      {/* G12.9：固定提示，呼應「不落地」定案。 */}
      <p className="flex items-center gap-1.5 rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
        <Info className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        不落地保存，請自行複製
      </p>

      {/* 票 S1-01：這道法務掃描的能力邊界揭露，一頁只顯示一次，不逐區塊重複。 */}
      <p className="text-xs text-muted-foreground">{result.scan_note}</p>

      <div className="flex justify-end">
        <button
          type="button"
          onClick={onRegenerate}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-sm text-secondary transition-colors hover:border-primary hover:text-primary",
            PRESS_FEEDBACK,
          )}
        >
          <RefreshCw className="h-4 w-4" aria-hidden="true" />
          重生
        </button>
      </div>
    </div>
  );
}

function SectionShell({
  Icon,
  title,
  count,
  headerExtra,
  children,
}: {
  Icon: ComponentType<{ className?: string }>;
  title: string;
  count: number;
  headerExtra?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
        <Icon className="h-4 w-4 text-primary" aria-hidden="true" />
        {title}
        <span className="font-bold text-foreground">・{count}</span>
        {headerExtra && <span className="ml-auto">{headerExtra}</span>}
      </div>
      {children}
    </div>
  );
}

/** 提示詞單則：預設兩行截斷（一次要看 10 則），長的才給展開鈕。截斷只是視覺，複製永遠複製
 * 全文。 */
function PromptRow({ index, content }: { index: number; content: string }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="flex items-start gap-2 rounded-md border border-border bg-background px-3 py-2 text-sm">
      <span className="shrink-0 font-bold text-muted-foreground">{index + 1}</span>
      <div className="min-w-0 flex-1">
        <p className={cn("text-foreground", !expanded && "line-clamp-2")}>{content}</p>
        {content.length > 60 && (
          <button
            type="button"
            onClick={() => setExpanded((prev) => !prev)}
            className="text-xs text-primary hover:underline"
          >
            {expanded ? "收合" : "展開"}
          </button>
        )}
      </div>
      <CopyIconButton ariaLabel="複製這則提示詞" getText={() => content} />
    </div>
  );
}

/** 腳本單支：`<details>` 原生折疊（鍵盤操作、螢幕閱讀器展開收合都是瀏覽器自己來，不自刻
 * 一套）。內容是後端寫死的 JSON 形狀，用既有 `parseVideoScript()` 解，解不開就原樣顯示，
 * 不整頁炸掉。第一段台詞是後端的 Hook 插槽佔位字串，原樣顯示，前端不改寫。 */
function ScriptCard({ index, component }: { index: number; component: QuickGenerateComponent }) {
  const parsed = parseVideoScript(component.content);
  if (!parsed) {
    return (
      <div className="rounded-md border border-border px-3 py-2 text-sm text-foreground">
        {component.content}
        <ComplianceBadges hits={component.compliance_hits} />
      </div>
    );
  }

  const copyText =
    `【${parsed.framework}】\n` +
    parsed.segments.map((seg) => `${seg.label}｜${seg.dialogue}｜${seg.visual}`).join("\n");

  return (
    <details className="group rounded-md border border-border">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-sm font-medium text-foreground">
        <Clapperboard className="h-4 w-4 text-primary" aria-hidden="true" />
        腳本 {index + 1}
        <span className="text-primary">・{parsed.framework}</span>
        <ChevronDown
          className="ml-auto h-4 w-4 text-muted-foreground transition-transform group-open:rotate-180 motion-reduce:transition-none"
          aria-hidden="true"
        />
      </summary>
      <div className="border-t border-border px-3 py-2">
        <ComplianceBadges hits={component.compliance_hits} />
        {parsed.segments.map((seg, segIndex) => (
          <div key={segIndex} className="flex gap-3 border-t border-border py-1.5 first:border-t-0">
            <span className="w-16 shrink-0 text-xs font-semibold text-muted-foreground">
              {seg.label}
            </span>
            <span className="min-w-0 flex-1 text-sm">
              <span className="block text-foreground">{seg.dialogue}</span>
              <span className="block text-xs text-muted-foreground">{seg.visual}</span>
            </span>
          </div>
        ))}
        <div className="mt-2 flex justify-end">
          <CopyIconButton ariaLabel={`複製腳本 ${index + 1}`} getText={() => copyText} />
        </div>
      </div>
    </details>
  );
}
