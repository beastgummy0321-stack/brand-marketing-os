const MOCK_DATA = {
  brand: {
    name: "沐光咖啡 LumiBrew",
    assistantName: "LumiBrew 投放助理",
    url: "lumibrew.example.com",
    monthlyBudget: 30000,
    goal: "線上訂閱訂單"
  },
  platforms: [
    { id: "meta", name: "Meta", glyph: "M", initialStatus: "unconnected", connectMs: 1200 },
    { id: "google", name: "Google", glyph: "G", initialStatus: "unconnected", connectMs: 1200 },
    { id: "tiktok", name: "TikTok", glyph: "T", initialStatus: "unconnected", connectMs: 1200 }
  ],
  tracking: {
    exampleUrl: "lumibrew.example.com",
    verifyMs: 1000,
    successText: "已偵測到追蹤碼"
  },
  analysis: {
    sellingPoints: ["每月寄到家，省下挑豆時間", "小批次烘焙，風味每週更新", "可隨時調整口味與寄送頻率"],
    audiences: ["想在家穩定喝到好咖啡的忙碌上班族", "喜歡探索風味、又不想研究器材的入門者"],
    competitors: [
      { name: "豆研 BeanLab", difference: "品項多但選擇成本高，我們用每月精選降低決策負擔。" },
      { name: "晨霧咖啡 MistBrew", difference: "偏單次購買，我們以訂閱節奏陪使用者養成每日咖啡習慣。" }
    ]
  },
  strategy: {
    budgets: [
      { id: "meta", name: "Meta", amount: 13500, percent: 45, tone: "dark" },
      { id: "google", name: "Google", amount: 9000, percent: 30, tone: "mid" },
      { id: "tiktok", name: "TikTok", amount: 7500, percent: 25, tone: "light" }
    ],
    objective: "先用內容找出高意願訂閱者，再把預算加到穩定成交的素材。",
    forecast: "預估 40～60 筆訂單"
  },
  materials: {
    meta: [
      [
        { title: "每天第一杯，交給剛好的風味", body: "每月精選兩款豆子，寄到你手上。", visual: "霧白背景上的手沖壺與咖啡杯線稿" },
        { title: "不用猜今天喝什麼", body: "一個訂閱，把新鮮烘焙排進你的日常。", visual: "淺灰紙張與深綠咖啡豆色塊" }
      ],
      [
        { title: "你的咖啡習慣，從一包剛剛好開始", body: "依口味寄送，想換就換，沒有綁約壓力。", visual: "冷灰桌面上的訂閱盒與圓形標籤" },
        { title: "小批次烘焙，風味不隔夜", body: "每週更新產地與焙度，喝得到新鮮。", visual: "墨綠色塊與兩顆線稿咖啡豆" }
      ]
    ],
    google: [
      [
        { title: "沐光咖啡 LumiBrew｜每月咖啡豆訂閱", url: "lumibrew.example.com/subscription", lines: ["每月精選兩款新鮮烘焙咖啡豆，寄到家。", "依你的口味調整，隨時暫停或更換。"] },
        { title: "在家喝好咖啡｜沐光咖啡訂閱計畫", url: "lumibrew.example.com/coffee", lines: ["不用研究器材，也能找到適合你的風味。", "從第一杯開始，建立每天的咖啡節奏。"] }
      ],
      [
        { title: "新鮮烘焙咖啡豆，每月送到家", url: "lumibrew.example.com/fresh", lines: ["小批次烘焙，讓每次開箱都像第一次。", "選口味、選頻率，訂閱可以很有彈性。"] },
        { title: "咖啡訂閱推薦｜找到你的日常風味", url: "lumibrew.example.com/taste", lines: ["三分鐘選出適合你的風味方向。", "沐光咖啡陪你把好喝變成習慣。"] }
      ]
    ],
    tiktok: [
      [
        { cover: "深墨綠背景上的播放鍵與咖啡杯線稿", hook: "開場鉤子：你每天的第一杯，真的需要想那麼久嗎？", point: "賣點：每月兩款小批次新鮮烘焙，依口味寄到家。", cta: "CTA：今天選好，下一杯就不用等。" },
        { cover: "深灰紙感背景與冒熱氣的杯子線稿", hook: "開場鉤子：打開盒子的那一刻，先聞到的是新鮮。", point: "賣點：風味每週更新，訂閱也能隨時換。", cta: "CTA：讓沐光替你留一杯剛好的。" }
      ],
      [
        { cover: "黑綠背景上的兩包咖啡豆與播放鍵線稿", hook: "開場鉤子：如果每月都有一包新口味呢？", point: "賣點：小批次烘焙，從產地到焙度都說清楚。", cta: "CTA：滑到沐光，開始你的咖啡訂閱。" },
        { cover: "石墨色背景與手沖水流線稿", hook: "開場鉤子：忙到沒空研究，也能喝到好豆。", point: "賣點：三分鐘選口味，照你的節奏送到家。", cta: "CTA：先試一個月，再決定要不要繼續。" }
      ]
    ]
  },
  launch: {
    dailyCap: 1500,
    schedule: "即日起～月底",
    pauseOptions: [3, 6, 12],
    defaultPauseHours: 6
  },
  performance: {
    before: {
      overview: { spend: 18600, conversions: 31, cost: 600, roas: 2.4, trend: [12, 18, 15, 22, 27, 30, 31] },
      meta: { spend: 8600, conversions: 16, cost: 538, roas: 2.7, trend: [6, 8, 7, 11, 13, 15, 16] },
      google: { spend: 5700, conversions: 10, cost: 570, roas: 2.3, trend: [4, 5, 6, 7, 8, 9, 10] },
      tiktok: { spend: 4300, conversions: 5, cost: 860, roas: 1.5, trend: [2, 3, 2, 4, 4, 5, 5] }
    },
    after: {
      overview: { spend: 19400, conversions: 42, cost: 462, roas: 3.1, trend: [14, 20, 19, 27, 34, 39, 42], changes: { spend: { direction: "up", percent: 4 }, conversions: { direction: "up", percent: 35 }, cost: { direction: "down", percent: 23 }, roas: { direction: "up", percent: 29 } } },
      meta: { spend: 9000, conversions: 21, cost: 429, roas: 3.2, trend: [7, 10, 9, 13, 16, 19, 21], changes: { spend: { direction: "up", percent: 5 }, conversions: { direction: "up", percent: 31 }, cost: { direction: "down", percent: 20 }, roas: { direction: "up", percent: 19 } } },
      google: { spend: 6100, conversions: 13, cost: 469, roas: 2.8, trend: [4, 6, 6, 8, 10, 12, 13], changes: { spend: { direction: "up", percent: 7 }, conversions: { direction: "up", percent: 30 }, cost: { direction: "down", percent: 18 }, roas: { direction: "up", percent: 22 } } },
      tiktok: { spend: 4300, conversions: 8, cost: 538, roas: 2.1, trend: [3, 4, 4, 6, 7, 8, 8], changes: { spend: { direction: "same", percent: 0 }, conversions: { direction: "up", percent: 60 }, cost: { direction: "down", percent: 37 }, roas: { direction: "up", percent: 40 } } }
    }
  },
  recommendations: [
    { type: "關掉", tone: "destructive", platform: "tiktok", title: "TikTok 那組素材成本太高，關掉它", reason: "前幾天的點擊很多，但還沒有形成穩定訂單。", impact: "省下 NT$3,000／月，其餘素材補上這筆預算" },
    { type: "加碼", tone: "primary", platform: "meta", title: "Meta 的訂閱素材反應最好，加一點預算", reason: "每筆成本低於平均，留言也更集中在訂閱意願。", impact: "每月多帶來約 6～8 筆訂單" },
    { type: "換素材", tone: "primary", platform: "google", title: "Google 換成更直接的搜尋標題", reason: "搜尋者已經在找咖啡訂閱，可以把好處說得更快。", impact: "預估每筆成本下降約 12%" }
  ],
  sidebar: {
    spent: 18600,
    budgetPercent: 62,
    currentStage: 1,
    updatedAt: "14:22"
  },
  copy: {
    summary: "花 {spend} 元，帶來 {conversions} 筆訂單",
    approved: "已核准 {count} 項優化",
    changeBadge: "{label} {arrow}{percent}%"
  }
};
