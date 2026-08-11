import { useState } from "react";
import type { SettingsData } from "@/lib/settingsApi";
import { saveModel } from "@/lib/settingsApi";
import { SectionCard } from "./shared/SectionCard";
import { SaveButton } from "./shared/SaveButton";
import { useFormSubmit } from "./shared/useFormSubmit";

/** 使用的模型小節（S15.19–S15.21）。文案沿用既有 `app/templates/settings.html:160-191`。 */
export function ModelSection({ data, onSaved }: { data: SettingsData; onSaved: () => void }) {
  const [model, setModel] = useState(data.current_model);
  const { saving, error, submit } = useFormSubmit(async () => {
    await saveModel(model);
    onSaved();
  });

  return (
    <SectionCard title="使用的模型">
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">要用哪一個模型？</span>
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          >
            {data.model_choices.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name} — {m.price_text}
              </option>
            ))}
          </select>
          <span className="text-xs text-muted-foreground">
            費率為美元計價、依用量計費；建檔精靈的花費列會即時換算顯示。
          </span>
        </label>
        {error && <p className="text-sm text-danger">{error}</p>}
        <div>
          <SaveButton saving={saving} label="儲存模型設定" />
        </div>
      </form>

      <details className="rounded-md border border-border p-3 text-sm">
        <summary className="cursor-pointer font-medium text-foreground">
          各任務預設模型與思考等級
        </summary>
        <p className="mt-2 text-muted-foreground">
          思考等級分五檔：低、中、高、超高、極高，等級愈高，模型想得愈深、花費也愈高。
        </p>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[28rem] text-left text-sm">
            <thead>
              <tr className="border-b border-border text-muted-foreground">
                <th className="py-1.5 pr-3 font-medium">任務</th>
                <th className="py-1.5 pr-3 font-medium">預設模型</th>
                <th className="py-1.5 font-medium">預設思考等級</th>
              </tr>
            </thead>
            <tbody>
              {data.task_model_thinking_table.map((row) => (
                <tr key={row.task_label} className="border-b border-border last:border-0">
                  <td className="py-1.5 pr-3 text-foreground">{row.task_label}</td>
                  <td className="py-1.5 pr-3 text-foreground">{row.model_label}</td>
                  <td className="py-1.5 text-foreground">{row.thinking_label}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </SectionCard>
  );
}
