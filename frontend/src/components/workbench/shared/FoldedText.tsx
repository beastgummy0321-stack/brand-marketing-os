/** 折疊線樣式（票 17 共用元件之一，跨畫面 3／4／5 側板重用）：超出字數預算的部分視覺變淡，
 * 加一條折疊線＋提示文字（Meta 會從這裡折疊），不截斷內容——使用者仍看得到、複製得到全文，
 * 只是清楚標出「貼上 Meta 後台後這裡開始有被折疊的風險」。`over_budget` 是後端算好的旗標
 * （字數守門三道關卡後仍超規格表預算），這裡只再拿 `charBudget` 算切點畫線，兩者算法一致
 * （後端 `len(content) > char_budget`，見 app/creative/theme_engine.py over_budget_items()）
 * ——真的沒超過時（例如旗標跟即時字數暫時對不上）就照原樣顯示，不硬畫一條假折疊線。 */
export function FoldedText({ content, charBudget }: { content: string; charBudget: number }) {
  if (content.length <= charBudget) {
    return <p className="text-sm text-foreground">{content}</p>;
  }

  return (
    <div>
      <p className="text-sm text-foreground">
        {content.slice(0, charBudget)}
        <span className="text-muted-foreground/50">{content.slice(charBudget)}</span>
      </p>
      <p className="mt-1 flex items-center gap-1.5 text-xs text-warning">
        <span aria-hidden="true" className="h-0 flex-1 border-t border-dashed border-warning/50" />
        Meta 會從這裡折疊（{charBudget} 字）
      </p>
    </div>
  );
}
