import { useState } from "react";
import type { SettingsData } from "@/lib/settingsApi";
import { saveBudget, saveCreativeRoot, savePromptHeader } from "@/lib/settingsApi";
import { SectionCard } from "./shared/SectionCard";
import { SaveButton } from "./shared/SaveButton";
import { useFormSubmit } from "./shared/useFormSubmit";

/** 素材資料夾與花費上限小節（S15.22–S15.28）。文案沿用既有
 * `app/templates/settings.html:193-249`。三個獨立表單（資料夾／提示詞開頭／花費上限），
 * 各自送出、各自鎖按鈕，互不影響（S15 失敗態：「任一小節單獨送出失敗：不影響其他小節」）。 */
export function AssetsSection({ data, onSaved }: { data: SettingsData; onSaved: () => void }) {
  const [creativeRoot, setCreativeRoot] = useState(data.creative_root);
  const rootForm = useFormSubmit(async () => {
    await saveCreativeRoot(creativeRoot);
    onSaved();
  });

  const [promptHeader, setPromptHeader] = useState(data.prompt_header);
  const headerForm = useFormSubmit(async () => {
    await savePromptHeader(promptHeader);
    onSaved();
  });

  const [budget, setBudget] = useState(String(data.intake_budget));
  const budgetForm = useFormSubmit(async () => {
    await saveBudget(Number(budget));
    onSaved();
  });

  return (
    <SectionCard
      title="素材圖檔資料夾"
      description="生圖工具做出來的圖不進系統，系統只記得它放在哪。每一期檔期在這個資料夾底下有自己的子資料夾。"
    >
      <div className="rounded-md border border-warning/40 bg-warning/10 p-3 text-sm">
        <p className="font-medium text-foreground">刪品牌或刪檔期時，這底下對應的子資料夾會一起被刪掉</p>
        <p className="mt-1 text-muted-foreground">
          請指到一個專門放素材的資料夾，不要指到還放著別的東西的地方（例如整顆雲端硬碟或磁碟機根目錄）。
          這些圖也不在每日備份範圍內。
        </p>
      </div>

      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          void rootForm.submit();
        }}
      >
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">資料夾完整路徑</span>
          <input
            type="text"
            value={creativeRoot}
            onChange={(e) => setCreativeRoot(e.target.value)}
            placeholder="例如 D:\行銷素材"
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
          <span className="text-xs text-muted-foreground">
            改路徑不會搬動已經倒進去的圖，舊資料夾要自己搬。
          </span>
        </label>
        {rootForm.error && <p className="text-sm text-danger">{rootForm.error}</p>}
        <div>
          <SaveButton saving={rootForm.saving} label="儲存素材資料夾" />
        </div>
      </form>

      <div className="flex flex-col gap-2 border-t border-border pt-4">
        <h3 className="text-sm font-medium text-foreground">整組複製提示詞的自訂開頭</h3>
        <p className="text-sm text-muted-foreground">
          素材工作檯的「整組複製」按下去時，會自動接上這段開頭。全站只有一份，不分品牌。
        </p>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            void headerForm.submit();
          }}
        >
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-foreground">自訂開頭</span>
            <textarea
              value={promptHeader}
              onChange={(e) => setPromptHeader(e.target.value)}
              rows={3}
              placeholder="例如：圖上文字一律平面實填，不要浮雕、液態字、金屬字、粗糙紋理、磨砂感"
              className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
            />
            <span className="text-xs text-muted-foreground">
              留白代表整組複製時不加開頭這一行。
            </span>
          </label>
          {headerForm.error && <p className="text-sm text-danger">{headerForm.error}</p>}
          <div>
            <SaveButton saving={headerForm.saving} label="儲存開頭" />
          </div>
        </form>
      </div>

      <div className="flex flex-col gap-2 border-t border-border pt-4">
        <h3 className="text-sm font-medium text-foreground">花費上限</h3>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            void budgetForm.submit();
          }}
        >
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-foreground">AI 生成的花費上限</span>
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">US$</span>
              <input
                type="number"
                step={1}
                min={0}
                value={budget}
                onChange={(e) => setBudget(e.target.value)}
                placeholder="例如 30"
                className="w-32 rounded-md border border-border px-3 py-2 text-sm text-foreground"
              />
            </div>
            <span className="text-xs text-muted-foreground">
              累計花費達到上限時會先停下來問你，不會直接繼續花錢。
            </span>
          </label>
          {budgetForm.error && <p className="text-sm text-danger">{budgetForm.error}</p>}
          <div>
            <SaveButton saving={budgetForm.saving} label="儲存花費上限" />
          </div>
        </form>
      </div>
    </SectionCard>
  );
}
