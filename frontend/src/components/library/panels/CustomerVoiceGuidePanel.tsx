import { X } from "lucide-react";
import { SidePanel } from "@/components/layout/SidePanel";

/** 「不知道去哪找顧客原話？」指南側板（契約 S5.38）：文案原樣照搬
 * `app/templates/customer_voice_guide.html:17-45`。 */
const CHANNEL_GUIDE: [string, string][] = [
  ["蝦皮商品評論", "買過的人對商品最直接的抱怨與稱讚，帶星等可分級看"],
  ["momo 商品評論", "同上，momo 客群偏主婦／家庭採購，語氣較生活化"],
  ["Dcard", "年輕族群的真實討論串，常見「求推薦」「踩雷心得」等高信號貼文"],
  ["PTT（相關看板）", "長文心得、比較文，用詞直接、較少行銷修飾"],
  ["FB 社團與粉專留言", "私密社團裡的同溫層討論，情緒濃度高；粉專留言可看到公開的顧客提問與抱怨"],
  ["客服對話紀錄", "最貼近真實購買障礙與售後困擾，沒有公開評論的美化濾鏡"],
];

export function CustomerVoiceGuidePanel({ onClose }: { onClose: () => void }) {
  return (
    <SidePanel ariaLabel="去哪找顧客原話" onClose={onClose} widthClassName="w-[32rem]">
      <div className="flex items-start justify-between gap-3 border-b border-border pb-4">
        <h2 className="font-display text-lg text-foreground">去哪找顧客原話</h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="關閉側板"
          className="rounded-md p-2 text-muted-foreground hover:bg-muted"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>

      <div className="flex flex-col gap-5 text-sm text-foreground">
        <section className="flex flex-col gap-2">
          <h3 className="font-display text-base">去哪個管道找</h3>
          <div className="overflow-x-auto rounded-md border border-border">
            <table className="w-full text-left text-sm">
              <thead className="bg-muted text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 font-medium">管道</th>
                  <th className="px-3 py-2 font-medium">適合找什麼</th>
                </tr>
              </thead>
              <tbody>
                {CHANNEL_GUIDE.map(([channel, fit]) => (
                  <tr key={channel} className="border-t border-border">
                    <td className="px-3 py-2 font-medium">{channel}</td>
                    <td className="px-3 py-2 text-muted-foreground">{fit}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="flex flex-col gap-2">
          <h3 className="font-display text-base">電商評論怎麼看</h3>
          <p>建議的閱讀順序：</p>
          <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
            <li>
              <strong className="text-foreground">先看中低星（2–3 星）</strong>
              ：買了但沒有全滿意，最誠實，常帶「其實⋯⋯」的但書。
            </li>
            <li>
              <strong className="text-foreground">再看低星（1 星）</strong>
              ：失敗案例，記得分清楚是產品問題還是物流／客服問題。
            </li>
            <li>
              <strong className="text-foreground">最後看高星（5 星）</strong>
              ：抓「顧客用什麼詞稱讚」，這是文案的正面素材庫。
            </li>
          </ul>
        </section>

        <section className="flex flex-col gap-2">
          <h3 className="font-display text-base">什麼算高價值原話</h3>
          <p>
            必須同時具備三個條件：<strong>具體情境</strong> ＋ <strong>情緒</strong> ＋{" "}
            <strong>顧客自己的用詞</strong>。
          </p>
          <p className="rounded-md border border-border bg-muted/40 p-3 text-muted-foreground">
            例如：「連續熬夜三天之後整個人腫到眼睛都腫，吃了兩天終於消下去，鬆一口氣」——有情境（熬夜三天）、
            有情緒（鬆一口氣）、有自己的用詞（腫到眼睛都腫）。
          </p>
          <p>反例（低價值、不值得收）：</p>
          <p className="rounded-md border border-border bg-muted/40 p-3 text-muted-foreground">
            「好用+1」「推推」「效果不錯」——沒有情境、沒有具體用詞，只是附和，抽不出任何可以放進文案的素材。
          </p>
        </section>
      </div>
    </SidePanel>
  );
}
