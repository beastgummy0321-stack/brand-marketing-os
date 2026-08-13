(function () {
  "use strict";

  window.MOCK = {
    accounts: {
      meta: { connected: false, label: "Meta Business · 沐光咖啡" },
      google: { connected: false, label: "Google Ads · LumiBrew TW" },
      tiktok: { connected: false, label: "TikTok Ads · @lumibrew.coffee" }
    },
    tracking: {
      url: "lumibrew.example.com/checkout",
      detected: false
    },
    brandInput: {
      pitch: "沐光咖啡，訂閱制咖啡豆，主打每月現烘直送"
    },
    aiAnalysis: {
      sellingPoints: [
        "每月現烘，寄出前才烘焙",
        "依口味選豆，免去挑選負擔",
        "定期直送，家中不再斷豆"
      ],
      audiences: [
        "25-44 歲，在家手沖的上班族",
        "重視新鮮度但沒有時間選豆的人"
      ],
      competitors: ["豆研 BeanLab", "晨霧咖啡 MistBrew"]
    },
    strategy: {
      budgetSplit: { meta: 45, google: 35, tiktok: 20 },
      objective: "線上訂閱訂單",
      forecastOrders: { low: 38, high: 52 },
      forecastRoas: { low: 2.2, high: 3.1 }
    },
    creatives: {
      meta: [
        [
          { title: "每天醒來，都有剛好的豆子", body: "每月現烘直送，不囤豆也不斷豆。\n首盒依你的口味推薦。", thumbColor: "#0EA5E9" },
          { title: "咖啡豆的新鮮，有日期可證明", body: "烘焙後快速寄出，把香氣留在你開袋時。\n訂閱方案可隨時調整。", thumbColor: "#14B8A6" }
        ],
        [
          { title: "不用再猜這包豆適不適合你", body: "三個問題配對風味，每月收到真正喝得完的量。\n今天開始你的咖啡日常。", thumbColor: "#F59E0B" },
          { title: "月底先補豆，不等最後一杯", body: "固定週期直送，也能跳過或更換風味。\n新鮮豆準時到門口。", thumbColor: "#F97316" }
        ]
      ],
      google: [
        [
          { headline: "現烘咖啡豆訂閱｜沐光咖啡", desc: "每月依口味配豆，現烘後直送到家。方案可彈性調整。", url: "lumibrew.example.com/subscription" },
          { headline: "每月新鮮咖啡豆送到家", desc: "不用囤豆、不怕斷豆。完成風味測驗，找到適合你的烘焙。", url: "lumibrew.example.com/fresh" }
        ],
        [
          { headline: "咖啡豆喝完前，自動補上", desc: "沐光訂閱按月現烘直送，可跳過月份，也能隨時換豆。", url: "lumibrew.example.com/never-empty" },
          { headline: "手沖咖啡豆推薦｜先選風味", desc: "果香、堅果或深焙，三步找到合口味的每月豆單。", url: "lumibrew.example.com/taste" }
        ]
      ],
      tiktok: [
        [
          { script: ["鏡頭：倒出家裡最後幾顆咖啡豆", "轉場：沐光包裹準時送達", "收尾：每月現烘，剛好不斷豆"], coverColor: "#2563EB" },
          { script: ["鏡頭：比較放一個月與剛開封的豆子", "字幕：香氣差別，鼻子最知道", "收尾：烘好就寄，開袋才是高峰"], coverColor: "#0891B2" }
        ],
        [
          { script: ["鏡頭：三張風味卡快速切換", "互動：酸甜、堅果、醇厚選一張", "收尾：你的下個月豆單已配好"], coverColor: "#D97706" },
          { script: ["鏡頭：晨間手沖計時 30 秒", "字幕：豆子不用想，早晨留給自己", "收尾：沐光每月把新鮮送來"], coverColor: "#EA580C" }
        ]
      ]
    },
    launchSettings: {
      dailyCapNT: 1000,
      noConversionPauseHours: 48
    },
    cockpit: {
      before: {
        health: "amber",
        spendToday: 823,
        ordersToday: 4,
        roas: 1.8,
        platforms: [
          { key: "meta", name: "Meta", spend: 412, orders: 2, cpo: 206, roas: 2.1, health: "green" },
          { key: "google", name: "Google", spend: 268, orders: 1, cpo: 268, roas: 1.2, health: "red" },
          { key: "tiktok", name: "TikTok", spend: 143, orders: 1, cpo: 143, roas: 1.9, health: "amber" }
        ]
      },
      after: {
        health: "green",
        spendToday: 796,
        ordersToday: 7,
        roas: 3.1,
        platforms: [
          { key: "meta", name: "Meta", spend: 328, orders: 2, cpo: 164, roas: 2.7, health: "green" },
          { key: "google", name: "Google", spend: 276, orders: 3, cpo: 92, roas: 4.2, health: "green" },
          { key: "tiktok", name: "TikTok", spend: 192, orders: 2, cpo: 96, roas: 2.8, health: "green" }
        ]
      }
    },
    decisionInbox: [
      { id: "p1", type: "stop", platform: "TikTok", title: "TikTok／素材B建議暫停", reason: "這則素材已花 NT$620，仍是零訂單。先停下可把預算留給有成交的素材。", impact: "預估月省 NT$1,200", icon: "pause" },
      { id: "p2", type: "boost", platform: "Google", title: "Google／搜尋廣告加碼", reason: "轉換率是平均的 2.3 倍，但預算常在下午提早用完。", impact: "預估月增 8-10 筆", icon: "trend" },
      { id: "p3", type: "swap", platform: "Meta", title: "Meta／換上新素材", reason: "同一批素材成效已連續 7 天下滑。換新版本可降低重複曝光疲勞。", impact: "每筆成本預估降 15%", icon: "refresh" },
      { id: "p4", type: "stop", platform: "Meta", title: "Meta／受眾A建議縮小", reason: "這群受眾花費佔比偏高，已連續 3 天沒有訂單。", impact: "預估月省 NT$450", icon: "warning" }
    ],
    performance: {
      before: {
        summary: "花823元帶來4筆訂單，每筆成本NT$206",
        days: ["08/07", "08/08", "08/09", "08/10", "08/11", "08/12", "08/13"],
        spend: [630, 712, 684, 755, 790, 810, 823],
        orders: [2, 2, 3, 2, 3, 4, 4]
      },
      after: {
        summary: "花796元帶來7筆訂單，每筆成本NT$114",
        days: ["08/07", "08/08", "08/09", "08/10", "08/11", "08/12", "08/13"],
        spend: [640, 688, 701, 728, 754, 778, 796],
        orders: [2, 3, 3, 5, 6, 7, 7]
      }
    }
  };
}());
