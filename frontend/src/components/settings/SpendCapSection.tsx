import { useState } from "react";
import type { SettingsData } from "@/lib/settingsApi";
import { saveBudget } from "@/lib/settingsApi";
import { SectionCard } from "./shared/SectionCard";
import { SaveButton } from "./shared/SaveButton";
import { useFormSubmit } from "@/lib/useFormSubmit";

/** 花費上限小節（S15.22–S15.28；票 storage-04 刪掉同卡的素材資料夾表單後只剩這個）。 */
export function SpendCapSection({ data, onSaved }: { data: SettingsData; onSaved: () => void }) {
  const [budget, setBudget] = useState(String(data.intake_budget));
  const budgetForm = useFormSubmit(async () => {
    await saveBudget(Number(budget));
    onSaved();
  });

  return (
    <SectionCard
      title="花費上限"
      description="這裡設定建檔精靈等 AI 生成功能，單一品牌可以花到多少錢。"
    >
      <div className="flex flex-col gap-2">
        <h3 className="text-sm font-medium text-foreground">單一品牌的花費上限</h3>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            void budgetForm.submit();
          }}
        >
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-foreground">建檔精靈等 AI 生成的花費上限</span>
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
              只管單一品牌、只算這個品牌從頭到現在的累計花費，不會每月歸零；累計達到上限時會先停下來問你，
              不會直接繼續花錢。跟「AI 金鑰」小節裡整個組織每月自動歸零的上限是不同的兩道關卡。
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
