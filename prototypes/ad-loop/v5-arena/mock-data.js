window.ARENA_DATA = {
  platforms: [
    { id: "meta", name: "Meta", connectState: false },
    { id: "google", name: "Google", connectState: false },
    { id: "tiktok", name: "TikTok", connectState: false }
  ],
  trackingDetected: false,
  analysis: {
    sellingPoints: ["每日新鮮烘焙", "小批次嚴選豆", "訂閱免運到家"],
    audiences: ["重視風味的居家沖煮者", "想固定補豆的忙碌上班族"],
    competitors: ["豆研 BeanLab", "晨霧咖啡 MistBrew"]
  },
  strategy: {
    budgetSplit: { meta: 45, google: 35, tiktok: 20 },
    goal: "線上訂閱訂單",
    estimateRange: "預估月訂單 55–80 筆"
  },
  creativeSetA: [
    { id: "a-meta-01", platform: "Meta", type: "image_text", thumbnailSvgSeed: "orange-beans", title: "今天烘，明天到", bodyCopy: "新鮮烘焙咖啡豆，訂閱每月送到家。" },
    { id: "a-meta-02", platform: "Meta", type: "image_text", thumbnailSvgSeed: "green-cup", title: "你的固定好咖啡", bodyCopy: "選風味、定頻率，忙也能喝到剛好的豆。" },
    { id: "a-google-01", platform: "Google", type: "search_text", thumbnailSvgSeed: "blue-search", title: "手沖咖啡豆訂閱｜LumiBrew", headline: "新鮮烘焙・每月到貨", description: "小批次嚴選咖啡豆，訂閱免運。" },
    { id: "a-google-02", platform: "Google", type: "search_text", thumbnailSvgSeed: "gold-search", title: "咖啡豆推薦｜沐光咖啡", headline: "找到你的日常風味", description: "在家手沖也能喝到穩定好味道。" },
    { id: "a-tiktok-01", platform: "TikTok", type: "video_script", thumbnailSvgSeed: "red-pour", title: "15 秒看懂訂閱咖啡", bodyCopy: "開箱→磨豆→第一口，讓新鮮感自己說服你。", coverDescription: "暖紅背景、手撕 LumiBrew 訂閱箱，中央疊上白字「15 秒看懂訂閱咖啡」，右下角放冒熱氣的咖啡杯。", videoScript: [
      { time: "0–3 秒", visual: "俯拍撕開訂閱箱，鏡頭切到包裝上的烘焙日期。", audio: "字幕：今天烘，明天到。" },
      { time: "4–8 秒", visual: "近拍咖啡豆落入磨豆機，接著快速帶到濾杯注水。", audio: "旁白：每月一包，剛好喝完再補。" },
      { time: "9–12 秒", visual: "慢動作倒入玻璃杯，第一口的蒸氣填滿畫面。", audio: "字幕：新鮮度，自己會說服你。" },
      { time: "13–15 秒", visual: "訂閱方案卡與手機點擊按鈕同框，品牌標誌停在右下角。", audio: "旁白：選你的風味，點擊開始訂閱。" }
    ] },
    { id: "a-tiktok-02", platform: "TikTok", type: "video_script", thumbnailSvgSeed: "lime-timer", title: "忙碌日的 30 秒沖煮", bodyCopy: "固定補豆不必記，打開包裹就能開始。", coverDescription: "螢光綠計時器與咖啡濾杯並排，左側大字「30 秒沖煮」，背景是忙碌桌面與剛拆開的豆袋。", videoScript: [
      { time: "0–4 秒", visual: "手機行事曆跳出『補豆日』，手把新豆袋放到桌上。", audio: "字幕：忙到忘記買豆？" },
      { time: "5–12 秒", visual: "一鏡到底倒豆、研磨、放濾紙，計時器從 30 秒倒數。", audio: "旁白：訂閱幫你記住下一包。" },
      { time: "13–22 秒", visual: "熱水繞圈注入，切換三個快速特寫：粉層、香氣、液面。", audio: "字幕：固定風味，省下選豆時間。" },
      { time: "23–30 秒", visual: "上班族拿起杯子出門，畫面收在『每月自動到貨』按鈕。", audio: "旁白：今天就選你的下一包。" }
    ] }
  ],
  creativeSetB: [
    { id: "b-meta-01", platform: "Meta", type: "image_text", thumbnailSvgSeed: "coral-morning", title: "一杯，替今天開場", bodyCopy: "早晨需要的香氣，按月替你準備好。" },
    { id: "b-meta-02", platform: "Meta", type: "image_text", thumbnailSvgSeed: "teal-box", title: "不再喝到放太久的豆", bodyCopy: "新鮮度有節奏，訂閱你的下一包。" },
    { id: "b-google-01", platform: "Google", type: "search_text", thumbnailSvgSeed: "slate-search", title: "精品咖啡豆定期配送", headline: "訂閱你的每月風味", description: "從淺焙到深焙，選好再送到家。" },
    { id: "b-google-02", platform: "Google", type: "search_text", thumbnailSvgSeed: "amber-search", title: "手沖咖啡豆 新鮮烘焙", headline: "今天烘，快速出貨", description: "小批次烘焙，讓每一杯都保有香氣。" },
    { id: "b-tiktok-01", platform: "TikTok", type: "video_script", thumbnailSvgSeed: "violet-pour", title: "這包豆子為何每月來", bodyCopy: "一個訂閱，換掉臨時找豆的焦慮。", coverDescription: "紫色漸層桌面上，訂閱豆袋從畫面上方落下，中央大字「為何每月來」，角落貼一枚『自動到貨』標籤。", videoScript: [
      { time: "0–3 秒", visual: "空咖啡罐被倒置，最後一顆豆滾出來，鏡頭定格在驚訝表情。", audio: "字幕：又喝完了，現在才想買？" },
      { time: "4–9 秒", visual: "畫面切成月曆翻頁，LumiBrew 豆袋在每個月份準時出現。", audio: "旁白：訂閱讓下一包準時來。" },
      { time: "10–15 秒", visual: "撕袋、聞香、倒豆三個節奏剪接，包裝日期清楚入鏡。", audio: "字幕：每次打開，都是新鮮烘焙。" },
      { time: "16–20 秒", visual: "手機顯示配送提醒，手指按下『訂閱』，畫面停在 CTA。", audio: "旁白：把找豆焦慮，換成固定好咖啡。" }
    ] },
    { id: "b-tiktok-02", platform: "TikTok", type: "video_script", thumbnailSvgSeed: "yellow-scale", title: "咖啡新手也能選風味", bodyCopy: "三個問題，找到你會喜歡的下一包。", coverDescription: "黃色電子秤、三張風味卡與咖啡豆袋平拍，頂端大字「新手選豆 3 問題」，用箭頭指向風味卡。", videoScript: [
      { time: "0–4 秒", visual: "三張風味卡像選擇題一樣彈出：果香、堅果、可可。", audio: "字幕：新手選豆，只要回答三題。" },
      { time: "5–10 秒", visual: "手指依序點選『喜歡酸香嗎？』『平常怎麼沖？』兩個選項。", audio: "旁白：先選你喜歡的味道。" },
      { time: "11–18 秒", visual: "推薦結果卡翻開，對應豆袋與刻度清楚顯示。", audio: "字幕：你的第一包，直接配好。" },
      { time: "19–24 秒", visual: "新手沖出第一杯，鏡頭拉遠露出訂閱按鈕與配送日期。", audio: "旁白：回答三題，下一包就交給我們。" }
    ] }
  ],
  launchConfig: {
    monthlyBudget: 30000,
    dailyCap: 1500,
    autoStopRule: "連續 3 天 0 轉換自動暫停",
    schedule: { start: "2026-08-15", end: "2026-09-14" }
  },
  arenaCardsBefore: [
    { id: "card-a-meta-01", creativeId: "a-meta-01", column: "generating", stats: { spend: 0, orders: 0, cpa: 0, roas: 0 }, eliminatedReason: "" },
    { id: "card-a-meta-02", creativeId: "a-meta-02", column: "generating", stats: { spend: 0, orders: 0, cpa: 0, roas: 0 }, eliminatedReason: "" },
    { id: "card-a-google-01", creativeId: "a-google-01", column: "generating", stats: { spend: 0, orders: 0, cpa: 0, roas: 0 }, eliminatedReason: "" },
    { id: "card-a-google-02", creativeId: "a-google-02", column: "generating", stats: { spend: 0, orders: 0, cpa: 0, roas: 0 }, eliminatedReason: "" },
    { id: "card-a-tiktok-01", creativeId: "a-tiktok-01", column: "generating", stats: { spend: 0, orders: 0, cpa: 0, roas: 0 }, eliminatedReason: "" },
    { id: "card-a-tiktok-02", creativeId: "a-tiktok-02", column: "generating", stats: { spend: 0, orders: 0, cpa: 0, roas: 0 }, eliminatedReason: "" }
  ],
  arenaCardsAfter: [
    { id: "card-a-meta-01", creativeId: "a-meta-01", column: "scaling", stats: { spend: 2120, orders: 8, cpa: 265, roas: 5.2 }, eliminatedReason: "" },
    { id: "card-a-meta-02", creativeId: "a-meta-02", column: "testing", stats: { spend: 940, orders: 2, cpa: 470, roas: 2.1 }, eliminatedReason: "" },
    { id: "card-a-google-01", creativeId: "a-google-01", column: "scaling", stats: { spend: 1180, orders: 6, cpa: 197, roas: 4.8 }, eliminatedReason: "" },
    { id: "card-a-google-02", creativeId: "a-google-02", column: "eliminated", stats: { spend: 310, orders: 0, cpa: 0, roas: 0 }, eliminatedReason: "連續 3 天 0 轉換" },
    { id: "card-a-tiktok-01", creativeId: "a-tiktok-01", column: "testing", stats: { spend: 270, orders: 1, cpa: 270, roas: 1.7 }, eliminatedReason: "" },
    { id: "card-a-tiktok-02", creativeId: "a-tiktok-02", column: "eliminated", stats: { spend: 0, orders: 0, cpa: 0, roas: 0 }, eliminatedReason: "素材互動率偏低" }
  ],
  summaryBefore: { spend: 4820, orders: 12, cpa: 402, roas: 3.1, trend7d: [2.1, 2.4, 2.0, 2.8, 2.6, 3.0, 3.1] },
  summaryAfter: { spend: 5260, orders: 19, cpa: 277, roas: 4.6, trend7d: [2.8, 3.0, 2.9, 3.5, 3.8, 4.2, 4.6] },
  proposals: [
    { id: "proposal-scale", type: "加碼", targetCardId: "card-a-meta-01", reasonPlain: "這張素材每花 1 元，帶回的訂單價值最高。", expectedImpact: "把預算移過來，預計多帶回 3–5 筆訂單。", effect: "scale" },
    { id: "proposal-stop", type: "關掉", targetCardId: "card-a-google-02", reasonPlain: "連續 3 天沒有轉換，繼續燒會浪費預算。", expectedImpact: "每天省下約 NT$100，留給更會贏的素材。", effect: "eliminate" },
    { id: "proposal-refresh", type: "換素材", targetCardId: "card-a-tiktok-02", reasonPlain: "互動率低，觀眾在前 2 秒就滑走了。", expectedImpact: "補一張新腳本，讓測試欄保持有挑戰者。", effect: "replace" }
  ]
};
