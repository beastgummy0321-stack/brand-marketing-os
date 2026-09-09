import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { CopyIconButton } from "@/components/layout/CopyIconButton";
import { Badge } from "@/components/layout/ui/badge";
import { Button } from "@/components/layout/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/layout/ui/dialog";
import { Input } from "@/components/layout/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/layout/ui/tabs";
import { fetchLibrary, type LibraryAsset } from "@/lib/libraryApi";
import { useAuthedImage } from "@/lib/useAuthedImage";
import {
  adoptOutput, closeBrief, deleteBrief, fetchStyles, reopenBrief, runPart,
  type BriefDetail as BriefDetailData, type ImageStyle, type WorkbenchOutput,
} from "@/lib/workbenchApi";
import { BUTTON_LABELS, IMAGE_PROMPT_ADVISORY, KIND_LABELS, LENGTH_HINTS, LENGTH_LABELS } from "./copy";
import { StatusBadge } from "./BriefList";

// app/workbench/repository.py `_PARTS_BY_KIND`（verified 2026-09-09）：哪個 kind 能跑哪個
// part——`ad_creative`（排程節點）兩個都能，其餘 kind 各自只有自己那個。
const PARTS_FOR_KIND: Record<string, string[]> = {
  ad_creative: ["copy", "image_prompt"],
  copy: ["copy"],
  image_prompt: ["image_prompt"],
  video_script: ["video_script"],
  free: ["free"],
};

// app/workbench/validate.py `_char_len()`：字數不算換行——跟伺服器 validation 訊息的字數
// 對得上（票面 contradiction check 第三條點名的陷阱）。
function charCount(text: string): number {
  return text.replace(/\n/g, "").length;
}

// jobs.py 把每一項驗證結果拼成 "✅ path：message" / "❌ path：message" 存進
// body_json.validation（字串陣列——不是票面示意 JSON 畫的 {path,ok,message} 物件陣列；
// 這裡照 app/workbench/jobs.py:191-193 真正寫回去的形狀讀，不照票面插圖）。
function failLine(validation: unknown, path: string): string | null {
  if (!Array.isArray(validation)) return null;
  const prefix = `❌ ${path}：`;
  const hit = validation.find((v) => typeof v === "string" && v.startsWith(prefix));
  return typeof hit === "string" ? hit : null;
}

// 票 workbench-2/02（ablation §4）：每個任務檔都會請模型回 `warnings`（誠實的「這是佔位，
// 投放前核對」句子）——防守讀法跟 `app/schedule/state.py::_copy_summary` 同一條（過濾非字串
// 元素，不是「全部都是字串才收」）。
function modelWarnings(body: Record<string, unknown>): string[] {
  return Array.isArray(body.warnings)
    ? body.warnings.filter((w): w is string => typeof w === "string")
    : [];
}

function WarningsList({ warnings }: { warnings: string[] }) {
  if (warnings.length === 0) return null;
  return (
    <div className="flex flex-col gap-1 text-sm text-muted-foreground">
      <span className="text-xs font-medium">模型的提醒</span>
      <ul className="list-disc pl-5">
        {warnings.map((text, i) => (
          <li key={i}>{text}</li>
        ))}
      </ul>
    </div>
  );
}

function outputsFor(brief: BriefDetailData, part: string): WorkbenchOutput[] {
  return brief.outputs
    .filter((o) => o.part === part)
    .sort((a, b) => a.generation_round - b.generation_round);
}

function latestRound(outputs: WorkbenchOutput[]): number {
  return outputs.length ? outputs[outputs.length - 1].generation_round : 0;
}

/** 一張 brief 只有一個 status 欄（`run_part()` 檔頭），失敗時看不出是哪個 part 沒過——
 * ponytail: 猜「還沒有任何產出的 part」；多 part 的 kind（`ad_creative`）若失敗前已經有
 * 一個 part 產出過，這裡可能猜錯，日後真的需要再加一欄記錄「上次跑的是哪個 part」。 */
function failedPart(brief: BriefDetailData): string {
  const candidates = PARTS_FOR_KIND[brief.kind] ?? [];
  return (
    candidates.find((p) => !brief.parts[p] || brief.parts[p].latest_round === 0) ??
    candidates[0] ??
    "copy"
  );
}

function RoundSwitcher({
  outputs, selected, onSelect,
}: { outputs: WorkbenchOutput[]; selected: number; onSelect: (round: number) => void }) {
  if (outputs.length <= 1) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {outputs.map((o) => (
        <span key={o.generation_round} className="inline-flex items-center gap-1">
          <Button
            type="button"
            size="sm"
            variant={o.generation_round === selected ? "default" : "outline"}
            aria-pressed={o.generation_round === selected}
            onClick={() => onSelect(o.generation_round)}
          >
            第 {o.generation_round} 輪
          </Button>
          {o.adopted_at !== null && <Badge variant="secondary">已採用</Badge>}
        </span>
      ))}
    </div>
  );
}

function CopyPartCard({
  brandId, brief, busy, onChanged,
}: { brandId: string; brief: BriefDetailData; busy: boolean; onChanged: () => void }) {
  const outputs = outputsFor(brief, "copy");
  const [selectedRound, setSelectedRound] = useState<number | null>(null);
  const [lengthTab, setLengthTab] = useState<"short" | "medium" | "long">("short");
  const [localBusy, setLocalBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const round = selectedRound ?? latestRound(outputs);
  const output = outputs.find((o) => o.generation_round === round);
  const body = (output?.body_json ?? {}) as Record<string, unknown>;
  const validation = body.validation;
  const headlines = Array.isArray(body.headlines) ? body.headlines.map(String) : [];
  const descriptions = Array.isArray(body.descriptions) ? body.descriptions.map(String) : [];
  const warnings = modelWarnings(body);
  const disabled = busy || localBusy || brief.closed_at !== null;

  async function run(action: () => Promise<unknown>) {
    setLocalBusy(true);
    setActionError(null);
    try {
      await action();
      onChanged();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "處理失敗，請稍後再試。");
    } finally {
      setLocalBusy(false);
    }
  }

  function copyAllText(): string {
    const variants = Array.isArray(body[lengthTab]) ? body[lengthTab].map(String) : [];
    return [...variants, ...headlines, ...descriptions].join("\n\n");
  }

  return (
    <div className="surface">
      <div className="surface-header">
        <h2>文案</h2>
        {output && output.adopted_at !== null && <Badge variant="secondary">已採用</Badge>}
        <RoundSwitcher outputs={outputs} selected={round} onSelect={setSelectedRound} />
      </div>
      <div className="surface-body flex flex-col gap-4">
        {!output ? (
          <p className="text-sm text-muted-foreground">還沒有產出。</p>
        ) : (
          <>
            <Tabs value={lengthTab} onValueChange={(v) => setLengthTab(v as typeof lengthTab)}>
              <TabsList>
                <TabsTrigger value="short">{LENGTH_LABELS.short}</TabsTrigger>
                <TabsTrigger value="medium">{LENGTH_LABELS.medium}</TabsTrigger>
                <TabsTrigger value="long">{LENGTH_LABELS.long}</TabsTrigger>
              </TabsList>
              {(["short", "medium", "long"] as const).map((key) => (
                <TabsContent key={key} value={key} className="flex flex-col gap-3">
                  <p className="text-xs text-muted-foreground">{LENGTH_HINTS[key]}</p>
                  {(Array.isArray(body[key]) ? body[key].map(String) : []).map((text, i) => {
                    const fail = failLine(validation, `${key}[${i + 1}]`);
                    return (
                      <div key={i} className="flex flex-col gap-1 rounded-md border border-border p-3">
                        <div className="flex items-start justify-between gap-2">
                          <p className="whitespace-pre-wrap text-sm">{text}</p>
                          <CopyIconButton ariaLabel={`複製第 ${i + 1} 則`} getText={() => text} />
                        </div>
                        <span className="numeric text-xs text-muted-foreground">{charCount(text)} 字</span>
                        {fail && <p className="text-xs text-danger">{fail}</p>}
                      </div>
                    );
                  })}
                </TabsContent>
              ))}
            </Tabs>

            <div className="flex flex-col gap-2">
              <span className="text-xs font-medium text-muted-foreground">標題</span>
              {headlines.map((text, i) => (
                <div key={i} className="flex items-center justify-between gap-2 text-sm">
                  <span>{text}</span>
                  <CopyIconButton ariaLabel={`複製標題 ${i + 1}`} getText={() => text} />
                </div>
              ))}
            </div>
            <div className="flex flex-col gap-2">
              <span className="text-xs font-medium text-muted-foreground">說明</span>
              {descriptions.map((text, i) => (
                <div key={i} className="flex items-center justify-between gap-2 text-sm">
                  <span>{text}</span>
                  <CopyIconButton ariaLabel={`複製說明 ${i + 1}`} getText={() => text} />
                </div>
              ))}
            </div>
            <div>
              <CopyIconButton getText={copyAllText} label={BUTTON_LABELS.copyAll} ariaLabel="全部複製" />
            </div>
            <WarningsList warnings={warnings} />
          </>
        )}
        {actionError && (
          <p role="alert" className="text-sm text-danger">
            {actionError}
          </p>
        )}
        <div className="flex gap-2">
          <Button
            type="button"
            onClick={() => output && void run(() => adoptOutput(brandId, brief.id, output.id))}
            disabled={!output || output.adopted_at !== null || disabled}
          >
            {BUTTON_LABELS.adopt}
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => void run(() => runPart(brandId, brief.id, "copy"))}
            disabled={disabled}
          >
            {BUTTON_LABELS.runAgain}
          </Button>
        </div>
      </div>
    </div>
  );
}

function ImagePromptPartCard({
  brandId, brief, busy, onChanged,
}: { brandId: string; brief: BriefDetailData; busy: boolean; onChanged: () => void }) {
  const outputs = outputsFor(brief, "image_prompt");
  const [selectedRound, setSelectedRound] = useState<number | null>(null);
  const [requestedCount, setRequestedCount] = useState("");
  const [localBusy, setLocalBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [assets, setAssets] = useState<LibraryAsset[]>([]);
  const round = selectedRound ?? latestRound(outputs);
  const output = outputs.find((o) => o.generation_round === round);
  const body = (output?.body_json ?? {}) as Record<string, unknown>;
  const validation = body.validation;
  const rendered = Array.isArray(body.rendered) ? body.rendered.map(String) : [];
  const warnings = modelWarnings(body);

  useEffect(() => {
    fetchLibrary(brandId).then((data) => setAssets(data.assets)).catch(() => {});
  }, [brandId]);

  const copyOutputs = outputsFor(brief, "copy");
  const sourceCopy = copyOutputs.find((o) => o.adopted_at !== null) ?? copyOutputs[copyOutputs.length - 1];
  const sourceHeadlines = sourceCopy && Array.isArray(sourceCopy.body_json.headlines)
    ? sourceCopy.body_json.headlines : [];
  const onImageTexts = brief.request.on_image_texts ?? [];
  const noSourceForText = sourceHeadlines.length === 0 && onImageTexts.length === 0;

  const requestedCountValue = Number(requestedCount);
  const validRequestedCount =
    requestedCount !== "" && Number.isInteger(requestedCountValue) &&
    requestedCountValue >= 1 && requestedCountValue <= 30;
  const runDisabled =
    busy || localBusy || noSourceForText || !validRequestedCount || brief.closed_at !== null;
  // 票 workbench-2/03（issue-image-prompt-button-disabled-with-no-reason）：`title` 屬性
  // 只在滑鼠停留時才看得到，而且原本只講 `noSourceForText` 一種原因——按鈕灰掉的另外三種
  // 情況（工單關了、上一輪還沒完、條數沒填對）完全沒有說法。改成畫面上永遠看得到的一行字，
  // 四個原因照這個優先順序，第一個成立的原因就是使用者現在真正卡住的那個。
  const runDisabledReason = brief.closed_at !== null
    ? "工單已關閉，重新開啟後才能產"
    : busy || localBusy
    ? "等目前這輪完成"
    : noSourceForText
    ? "先產文案，或在工單填圖上文字"
    : !validRequestedCount
    ? "填 1～30 的條數"
    : null;

  async function handleRun() {
    setLocalBusy(true);
    setActionError(null);
    try {
      await runPart(brandId, brief.id, "image_prompt", requestedCountValue);
      onChanged();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "產出失敗，請稍後再試。");
    } finally {
      setLocalBusy(false);
    }
  }

  const photo = brief.product_id
    ? assets.find((a) => a.asset_kind === "product_photo" && a.product_id === brief.product_id)
    : undefined;
  const { src: photoSrc } = useAuthedImage(photo?.file_url);

  return (
    <div className="surface">
      <div className="surface-header">
        <h2>圖片提示詞</h2>
        {output && output.adopted_at !== null && <Badge variant="secondary">已採用</Badge>}
        <RoundSwitcher outputs={outputs} selected={round} onSelect={setSelectedRound} />
      </div>
      <div className="surface-body flex flex-col gap-4">
        {brief.kind === "image_prompt" && brief.source_kind === "manual" && onImageTexts.length > 0 && (
          <div className="flex flex-col gap-1 text-sm">
            <span className="text-xs font-medium text-muted-foreground">圖上文字</span>
            <ul className="list-disc pl-5">
              {onImageTexts.map((text, i) => (
                <li key={i}>{text}</li>
              ))}
            </ul>
          </div>
        )}

        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-foreground">要幾條提示詞</span>
            <Input
              type="number"
              min={1}
              max={30}
              value={requestedCount}
              onChange={(e) => setRequestedCount(e.target.value)}
              className="w-24 numeric"
            />
          </label>
          <span className="max-w-xs text-xs text-muted-foreground">{IMAGE_PROMPT_ADVISORY}</span>
          <Button
            type="button"
            onClick={() => void handleRun()}
            disabled={runDisabled}
          >
            {BUTTON_LABELS.runImagePrompt}
          </Button>
        </div>
        {runDisabledReason && (
          <p className="text-xs text-muted-foreground">{runDisabledReason}</p>
        )}

        {actionError && (
          <p role="alert" className="text-sm text-danger">
            {actionError}
          </p>
        )}

        {output && (
          <div className="flex gap-4">
            <div className="flex flex-1 flex-col gap-3">
              {rendered.map((text, i) => {
                const fail = failLine(validation, `prompts[${i + 1}]`);
                return (
                  <div key={i} className="flex flex-col gap-1 rounded-md border border-border p-3">
                    <div className="flex items-start justify-between gap-2">
                      <pre className="whitespace-pre-wrap font-sans text-xs">{text}</pre>
                      <CopyIconButton ariaLabel={`複製第 ${i + 1} 則提示詞`} getText={() => text} />
                    </div>
                    <span className="numeric text-xs text-muted-foreground">{charCount(text)} 字</span>
                    {fail && <p className="text-xs text-danger">{fail}</p>}
                  </div>
                );
              })}
            </div>
            <div className="w-32 shrink-0">
              {photo ? (
                <img
                  src={photoSrc ?? undefined}
                  alt="商品參考照"
                  className="h-32 w-32 rounded-md border border-border object-cover"
                />
              ) : (
                <p className="text-xs text-muted-foreground">
                  尚無商品參考照，圖片工具需要它才能保住商品外觀
                  {brief.product_id && (
                    <>
                      {"　"}
                      <Link
                        to={`/brands/${encodeURIComponent(brandId)}/library?tab=assets`}
                        className="text-primary underline-offset-4 hover:underline"
                      >
                        品牌智庫 → 官方素材
                      </Link>
                    </>
                  )}
                </p>
              )}
            </div>
          </div>
        )}
        {output && <WarningsList warnings={warnings} />}
      </div>
    </div>
  );
}

// 自由生成（free）唯一的呼叫端——items[] 是 {label, value} 物件（app/departments/workbench/
// free.md），不是任意鍵值，所以直接照這個形狀畫標籤區塊，不再猜 body_json 有哪些鍵。
function FreeformPartCard({
  brandId, brief, part, title, busy, onChanged,
}: {
  brandId: string; brief: BriefDetailData; part: string; title: string; busy: boolean;
  onChanged: () => void;
}) {
  const outputs = outputsFor(brief, part);
  const output = outputs[outputs.length - 1];
  const [localBusy, setLocalBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const body = (output?.body_json ?? {}) as Record<string, unknown>;
  const items = Array.isArray(body.items) ? body.items : [];
  const warnings = modelWarnings(body);

  async function handleRunAgain() {
    setLocalBusy(true);
    setActionError(null);
    try {
      await runPart(brandId, brief.id, part);
      onChanged();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "產出失敗，請稍後再試。");
    } finally {
      setLocalBusy(false);
    }
  }

  return (
    <div className="surface">
      <div className="surface-header">
        <h2>{title}</h2>
      </div>
      <div className="surface-body flex flex-col gap-3">
        {!output ? (
          <p className="text-sm text-muted-foreground">還沒有產出。</p>
        ) : (
          <>
            {items.map((item, i) => {
              const record = (item ?? {}) as Record<string, unknown>;
              const label = typeof record.label === "string" ? record.label : "";
              const value = typeof record.value === "string" ? record.value : "";
              return (
                <div key={i} className="flex flex-col gap-1 rounded-md border border-border p-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex flex-col gap-1">
                      <span className="text-xs font-medium text-muted-foreground">{label}</span>
                      <p className="whitespace-pre-wrap text-sm">{value}</p>
                    </div>
                    <CopyIconButton ariaLabel={`複製${label ? `「${label}」` : ""}`} getText={() => value} />
                  </div>
                </div>
              );
            })}
            <WarningsList warnings={warnings} />
          </>
        )}
        {actionError && (
          <p role="alert" className="text-sm text-danger">
            {actionError}
          </p>
        )}
        <div>
          <Button
            type="button" variant="outline" onClick={() => void handleRunAgain()}
            disabled={busy || localBusy}
          >
            {BUTTON_LABELS.runAgain}
          </Button>
        </div>
      </div>
    </div>
  );
}

function VideoScriptPartCard({
  brandId, brief, busy, onChanged,
}: { brandId: string; brief: BriefDetailData; busy: boolean; onChanged: () => void }) {
  const outputs = outputsFor(brief, "video_script");
  const [selectedRound, setSelectedRound] = useState<number | null>(null);
  const [requestedCount, setRequestedCount] = useState("");
  const [localBusy, setLocalBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const round = selectedRound ?? latestRound(outputs);
  const output = outputs.find((o) => o.generation_round === round);
  const body = (output?.body_json ?? {}) as Record<string, unknown>;
  const validation = body.validation;
  const scripts = Array.isArray(body.scripts) ? body.scripts : [];
  const hookPool = Array.isArray(body.hook_pool) ? body.hook_pool.map(String) : [];
  const warnings = modelWarnings(body);

  const requestedCountValue = Number(requestedCount);
  const validRequestedCount =
    requestedCount !== "" && Number.isInteger(requestedCountValue) &&
    requestedCountValue >= 1 && requestedCountValue <= 5;
  const runDisabled = busy || localBusy || !validRequestedCount || brief.closed_at !== null;
  // 票 workbench-2/03：跟圖片提示詞卡同一個道理（issue-image-prompt-button-disabled-with-no-reason），
  // 少一個 `noSourceForText`（影片腳本沒有這個來源限制）；條數上限是這張卡自己的 1～5
  // （上面 `validRequestedCount` 的邊界），不是圖片提示詞卡的 1～30。
  const runDisabledReason = brief.closed_at !== null
    ? "工單已關閉，重新開啟後才能產"
    : busy || localBusy
    ? "等目前這輪完成"
    : !validRequestedCount
    ? "填 1～5 的條數"
    : null;

  async function handleRun() {
    setLocalBusy(true);
    setActionError(null);
    try {
      await runPart(brandId, brief.id, "video_script", requestedCountValue);
      onChanged();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "產出失敗，請稍後再試。");
    } finally {
      setLocalBusy(false);
    }
  }

  return (
    <div className="surface">
      <div className="surface-header">
        <h2>影片腳本</h2>
        {output && output.adopted_at !== null && <Badge variant="secondary">已採用</Badge>}
        <RoundSwitcher outputs={outputs} selected={round} onSelect={setSelectedRound} />
      </div>
      <div className="surface-body flex flex-col gap-4">
        {!output ? (
          <p className="text-sm text-muted-foreground">還沒有產出。</p>
        ) : (
          scripts.map((script, i) => {
            const record = (script ?? {}) as Record<string, unknown>;
            const scriptTitle = typeof record.title === "string" ? record.title : "";
            const framework = typeof record.framework === "string" ? record.framework : "";
            const hook = typeof record.hook === "string" ? record.hook : "";
            const cta = typeof record.cta === "string" ? record.cta : "";
            const beats = Array.isArray(record.beats) ? record.beats : [];
            const fail = failLine(validation, `scripts[${i + 1}]`);
            return (
              <div key={i} className="flex flex-col gap-2 rounded-md border border-border p-3">
                <div className="flex items-start justify-between gap-2">
                  <span className="text-sm font-medium text-foreground">
                    {scriptTitle || `第 ${i + 1} 支`}
                  </span>
                  <CopyIconButton
                    ariaLabel={`複製第 ${i + 1} 支腳本`}
                    getText={() => JSON.stringify(record, null, 2)}
                  />
                </div>
                <span className="text-xs text-muted-foreground">框架：{framework}</span>
                <p className="text-sm">鉤子：{hook}</p>
                {beats.length > 0 && (
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-left text-muted-foreground">
                          <th className="pr-2 font-medium">時間</th>
                          <th className="pr-2 font-medium">畫面</th>
                          <th className="pr-2 font-medium">口白</th>
                          <th className="font-medium">字卡</th>
                        </tr>
                      </thead>
                      <tbody>
                        {beats.map((beat, bi) => {
                          const b = (beat ?? {}) as Record<string, unknown>;
                          return (
                            <tr key={bi} className="align-top">
                              <td className="pr-2">{String(b.t ?? "")}</td>
                              <td className="pr-2">{String(b.visual ?? "")}</td>
                              <td className="pr-2">{String(b.voice ?? "")}</td>
                              <td>{String(b.text ?? "")}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
                <p className="text-sm">CTA：{cta}</p>
                {fail && <p className="text-xs text-danger">{fail}</p>}
              </div>
            );
          })
        )}

        {hookPool.length > 0 && (
          <div className="flex flex-col gap-2">
            <span className="text-xs font-medium text-muted-foreground">Hook pool</span>
            {hookPool.map((text, i) => (
              <div key={i} className="flex items-center justify-between gap-2 text-sm">
                <span>{text}</span>
                <CopyIconButton ariaLabel={`複製第 ${i + 1} 個 hook`} getText={() => text} />
              </div>
            ))}
          </div>
        )}

        {output && <WarningsList warnings={warnings} />}

        {actionError && (
          <p role="alert" className="text-sm text-danger">
            {actionError}
          </p>
        )}
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-foreground">要幾支腳本</span>
            <Input
              type="number"
              min={1}
              max={5}
              value={requestedCount}
              onChange={(e) => setRequestedCount(e.target.value)}
              className="w-24 numeric"
            />
          </label>
          <Button type="button" onClick={() => void handleRun()} disabled={runDisabled}>
            {BUTTON_LABELS.runAgain}
          </Button>
        </div>
        {runDisabledReason && (
          <p className="text-xs text-muted-foreground">{runDisabledReason}</p>
        )}
      </div>
    </div>
  );
}

export function BriefDetail({
  brandId, brief, onChanged, onDeleted,
}: { brandId: string; brief: BriefDetailData; onChanged: () => void; onDeleted: () => void }) {
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [headerBusy, setHeaderBusy] = useState(false);
  const [headerError, setHeaderError] = useState<string | null>(null);
  const [styles, setStyles] = useState<ImageStyle[]>([]);

  useEffect(() => {
    fetchStyles().then(setStyles).catch(() => {});
  }, []);

  const busy = brief.status === "queued" || brief.status === "running";
  const styleLabel = styles.find((s) => s.key === brief.style_key)?.label ?? brief.style_key;
  const parts = PARTS_FOR_KIND[brief.kind] ?? [];

  async function handleToggleClose() {
    setHeaderBusy(true);
    setHeaderError(null);
    try {
      if (brief.closed_at !== null) await reopenBrief(brandId, brief.id);
      else await closeBrief(brandId, brief.id);
      onChanged();
    } catch (err) {
      setHeaderError(err instanceof Error ? err.message : "操作失敗，請稍後再試。");
    } finally {
      setHeaderBusy(false);
    }
  }

  async function handleDelete() {
    setHeaderBusy(true);
    setHeaderError(null);
    try {
      await deleteBrief(brandId, brief.id);
      setDeleteOpen(false);
      onDeleted();
    } catch (err) {
      setHeaderError(err instanceof Error ? err.message : "刪除失敗，請稍後再試。");
      setHeaderBusy(false);
    }
  }

  async function handleRetry() {
    setHeaderBusy(true);
    setHeaderError(null);
    try {
      await runPart(brandId, brief.id, failedPart(brief));
      onChanged();
    } catch (err) {
      setHeaderError(err instanceof Error ? err.message : "重新產出失敗，請稍後再試。");
    } finally {
      setHeaderBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-base font-semibold">{KIND_LABELS[brief.kind] ?? brief.kind}</h2>
          {brief.product_name && <span className="text-sm text-muted-foreground">{brief.product_name}</span>}
          <span className="text-sm text-muted-foreground">{styleLabel}</span>
          <StatusBadge brief={brief} />
        </div>
        <div className="flex items-center gap-2">
          {brief.source_kind === "schedule_node" && (
            <Button asChild variant="ghost" size="sm">
              <Link to={`/brands/${encodeURIComponent(brandId)}/schedule`}>{BUTTON_LABELS.toSchedule}</Link>
            </Button>
          )}
          <Button
            type="button" variant="ghost" size="sm" onClick={() => void handleToggleClose()}
            disabled={headerBusy}
          >
            {brief.closed_at !== null ? BUTTON_LABELS.reopen : BUTTON_LABELS.close}
          </Button>
          <Button
            type="button" variant="ghost" size="sm" onClick={() => setDeleteOpen(true)}
            disabled={headerBusy}
          >
            {BUTTON_LABELS.delete}
          </Button>
        </div>
      </div>

      {headerError && (
        <p role="alert" className="text-sm text-danger">
          {headerError}
        </p>
      )}

      {brief.status === "failed" && (
        <div className="surface p-4" role="alert">
          <p className="text-sm text-danger">{brief.last_error ?? "產出失敗。"}</p>
          <div className="mt-3">
            <Button type="button" variant="outline" onClick={() => void handleRetry()} disabled={headerBusy}>
              {BUTTON_LABELS.retry}
            </Button>
          </div>
        </div>
      )}

      {parts.includes("copy") && (
        <CopyPartCard brandId={brandId} brief={brief} busy={busy} onChanged={onChanged} />
      )}
      {parts.includes("image_prompt") && (
        <ImagePromptPartCard brandId={brandId} brief={brief} busy={busy} onChanged={onChanged} />
      )}
      {parts.includes("video_script") && (
        <VideoScriptPartCard brandId={brandId} brief={brief} busy={busy} onChanged={onChanged} />
      )}
      {parts.includes("free") && (
        <FreeformPartCard
          brandId={brandId} brief={brief} part="free" title="自由生成" busy={busy} onChanged={onChanged}
        />
      )}

      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>刪除這張工單？</DialogTitle>
            <DialogDescription>刪除這張工單會一起刪掉它的所有產出，無法復原。</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setDeleteOpen(false)} disabled={headerBusy}>
              取消
            </Button>
            <Button type="button" variant="destructive" onClick={() => void handleDelete()} disabled={headerBusy}>
              {BUTTON_LABELS.delete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
