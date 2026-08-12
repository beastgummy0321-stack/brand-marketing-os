import { useState } from "react";
import { SidePanel } from "@/components/layout/SidePanel";
import { INTERVIEW_AXES, submitInterview, type InterviewSubmitResult } from "@/lib/campaignsApi";
import { useFormSubmit } from "@/lib/useFormSubmit";

type Selection = Partial<Record<string, string[]>>;

function toggle(map: Selection, axisKey: string, value: string): Selection {
  const cur = map[axisKey] ?? [];
  const next = cur.includes(value) ? cur.filter((v) => v !== value) : [...cur, value];
  return { ...map, [axisKey]: next };
}

/** 前朝教訓訪談側板（契約 S7.14-S7.20）：四軸點選式訪談，全程選填。選項照抄
 * `app/ads/fingerprint.py` 定版四軸（`lib/campaignsApi.ts INTERVIEW_AXES`），同一軸值兩邊
 * 都勾的衝突訊息交給後端／假資料層算（`mocks/campaignsHandlers.ts`），這裡只負責畫面與送出。 */
export function InterviewPanel({
  brandId,
  onClose,
  onSubmitted,
}: {
  brandId: string;
  onClose: () => void;
  onSubmitted: (result: InterviewSubmitResult) => void;
}) {
  const [bad, setBad] = useState<Selection>({});
  const [good, setGood] = useState<Selection>({});
  const [note, setNote] = useState("");

  const form = useFormSubmit(async () => {
    const result = await submitInterview(brandId, { bad, good, note });
    onSubmitted(result);
  });

  return (
    <SidePanel ariaLabel="前朝教訓訪談" onClose={onClose} widthClassName="w-[36rem]">
      <div className="border-b border-border pb-4">
        <h2 className="font-display text-lg text-foreground">前朝教訓訪談</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          過去投放中，哪些方向試過沒效果、哪些方向確實有效？點選你記得的部分即可，全部欄位都選填，不勾也可以直接送出。
          「試過不行」的會先記成候選規則，等你確認才會真的避開；「這個有效」的會記成待驗證的假設，下一期開期時自動排進去驗證。
        </p>
      </div>

      <form
        className="flex flex-col gap-6"
        onSubmit={(e) => {
          e.preventDefault();
          void form.submit();
        }}
      >
        {INTERVIEW_AXES.map((axis) => (
          <fieldset key={axis.key} className="flex flex-col gap-2">
            <legend className="text-sm font-semibold text-foreground">
              {axis.label}：{axis.question}
            </legend>
            <div className="overflow-x-auto rounded-md border border-border">
              <table className="w-full text-left text-sm">
                <thead className="bg-muted text-xs text-muted-foreground">
                  <tr>
                    <th className="px-3 py-1.5 font-medium">選項</th>
                    <th className="w-20 px-3 py-1.5 text-center font-medium">試過不行</th>
                    <th className="w-20 px-3 py-1.5 text-center font-medium">這個有效</th>
                  </tr>
                </thead>
                <tbody>
                  {axis.values.map((option) => (
                    <tr key={option.value} className="border-t border-border">
                      <td className="px-3 py-1.5 text-foreground">{option.label}</td>
                      <td className="px-3 py-1.5 text-center">
                        <input
                          type="checkbox"
                          checked={(bad[axis.key] ?? []).includes(option.value)}
                          onChange={() => setBad((prev) => toggle(prev, axis.key, option.value))}
                        />
                      </td>
                      <td className="px-3 py-1.5 text-center">
                        <input
                          type="checkbox"
                          checked={(good[axis.key] ?? []).includes(option.value)}
                          onChange={() => setGood((prev) => toggle(prev, axis.key, option.value))}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </fieldset>
        ))}

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">補充說明（選填）</span>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={3}
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
          <span className="text-xs text-muted-foreground">這段文字只會存起來備查，不會進入 AI 生成內容的依據。</span>
        </label>

        {form.error && <p className="text-sm text-danger">{form.error}</p>}
        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={form.saving}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {form.saving ? "送出中…" : "送出"}
          </button>
          <button
            type="button"
            onClick={onClose}
            disabled={form.saving}
            className="text-sm text-muted-foreground hover:underline"
          >
            跳過，之後再說
          </button>
        </div>
      </form>
    </SidePanel>
  );
}
