/* 唯一假資料進入點：未來串接後端時，只替換這個檔案。 */
(function () {
  function isoDate(offsetDays) {
    var date = new Date();
    date.setDate(date.getDate() + offsetDays);
    return date.getFullYear() + '-' + String(date.getMonth() + 1).padStart(2, '0') + '-' + String(date.getDate()).padStart(2, '0');
  }

  window.mockData = {
    accounts: {
      meta: { connected: false, name: 'Meta' },
      google: { connected: false, name: 'Google' },
      tiktok: { connected: false, name: 'TikTok' }
    },
    tracking: { url: 'lumibrew.example.com', detected: false },
    goal: { url: 'lumibrew.example.com', statement: '每月 50 筆訂閱', budget: 30000 },
    aiAnalysis: {
      sellingPoints: ['新鮮烘焙後 48 小時內出貨', '訂閱週期可自由調整', '每包附沖煮風味卡'],
      audiences: ['重視日常儀式感的都會上班族', '想在家喝精品咖啡的入門者'],
      competitors: ['豆研 BeanLab', '晨霧咖啡 MistBrew']
    },
    portfolio: {
      portfolioBefore: {
        allocation: [
          { platform: 'Meta', pct: 45, amount: 13500 },
          { platform: 'Google', pct: 35, amount: 10500 },
          { platform: 'TikTok', pct: 20, amount: 6000 }
        ]
      },
      portfolioAfter: {
        allocation: [
          { platform: 'Meta', pct: 40, amount: 12000 },
          { platform: 'Google', pct: 48, amount: 14400 },
          { platform: 'TikTok', pct: 12, amount: 3600 }
        ]
      },
      predictedRange: { low: 42, high: 58 },
      risk: {
        level: '中',
        reasons: ['TikTok 新素材尚無成效數據', '訂閱商品需先累積再行銷受眾', 'Google 關鍵字競價在週末偏高']
      }
    },
    creatives: {
      meta: {
        batch1: [
          { title: '把週一的香氣，留給自己', body: '每月一包，讓好咖啡準時到家。', color: '#D6E4F0' },
          { title: '本週烘焙，這週就喝到', body: '沐光訂閱，從第一杯開始認識你的風味。', color: '#E7DED0' }
        ],
        batch2: [
          { title: '今晚的手沖，已替你備好', body: '選一個週期，讓豆子跟著生活到家。', color: '#DAE8D9' },
          { title: '一杯咖啡，留一段自己的時間', body: '訂閱即享首月風味指南與免運。', color: '#E8D9D5' }
        ]
      },
      google: {
        batch1: [
          { headline1: '咖啡豆訂閱｜沐光咖啡', headline2: '48 小時新鮮出貨', description: '依您的節奏配送精品咖啡豆，首月免運。' },
          { headline1: '精品咖啡豆定期配送', headline2: '訂閱週期自由選', description: '每包都有風味卡，從第一杯開始找到喜好。' }
        ],
        batch2: [
          { headline1: '每月咖啡訂閱推薦', headline2: '沐光咖啡新鮮烘焙', description: '每月準時到家，今天開始您的手沖日常。' },
          { headline1: '咖啡豆訂閱方案', headline2: '新手也能輕鬆選', description: '依沖煮方式挑選，訂閱方案彈性可調整。' }
        ]
      },
      tiktok: {
        batch1: [
          { color: '#D6D8EC', points: ['0–2 秒：撕開剛到貨的咖啡包', '3–7 秒：手沖冒出第一段香氣', '8–12 秒：一句「好咖啡自己會到家」'] },
          { color: '#DCE5D7', points: ['0–3 秒：週一早晨的安靜畫面', '4–8 秒：磨豆與注水特寫', '9–13 秒：展示訂閱配送日期'] }
        ],
        batch2: [
          { color: '#E7D9D0', points: ['0–2 秒：打開風味卡與咖啡包', '3–8 秒：對照風味卡沖煮', '9–14 秒：展示自由調整配送週期'] },
          { color: '#D5E3E1', points: ['0–3 秒：空的咖啡罐', '4–8 秒：配送咖啡剛好補滿', '9–12 秒：一句「不怕忘記補豆」'] }
        ]
      }
    },
    riskControls: { dailyCap: 5000, autoPauseThreshold: 5 },
    schedule: { start: isoDate(0), end: isoDate(30) },
    performance: {
      before: {
        spend: 12500, orders: 19, cac: 658, roas: 1.62, goalRate: 38,
        trend: { days: ['一', '二', '三', '四', '五', '六', '日'], actual: [2, 3, 4, 5, 5, 7, 8], forecastLow: [2, 3, 3, 4, 5, 5, 6], forecastHigh: [4, 5, 7, 8, 10, 12, 14] },
        byPlatform: [
          { platform: 'Meta', spend: 5600, orders: 8, cac: 700, roas: 1.42 },
          { platform: 'Google', spend: 4500, orders: 9, cac: 500, roas: 2.12 },
          { platform: 'TikTok', spend: 2400, orders: 2, cac: 1200, roas: 0.74 }
        ]
      },
      after: {
        spend: 12100, orders: 53, cac: 228, roas: 3.42, goalRate: 106,
        trend: { days: ['一', '二', '三', '四', '五', '六', '日'], actual: [6, 13, 20, 28, 35, 45, 53], forecastLow: [4, 10, 16, 23, 30, 38, 46], forecastHigh: [8, 16, 25, 34, 43, 53, 62] },
        byPlatform: [
          { platform: 'Meta', spend: 5100, orders: 21, cac: 243, roas: 3.04 },
          { platform: 'Google', spend: 5700, orders: 29, cac: 197, roas: 4.01 },
          { platform: 'TikTok', spend: 1300, orders: 3, cac: 433, roas: 1.23 }
        ]
      }
    },
    rebalanceProposals: [
      { action: '關閉', target: 'TikTok 素材 B', reason: '連續五筆花費沒有訂單', impact: '省 NT$1,200／週', selected: true },
      { action: '加碼', target: 'Google 搜尋', reason: '高意圖搜尋的成本最低', impact: '多 8 筆／週', selected: true },
      { action: '換素材', target: 'Meta 主視覺', reason: '開箱畫面停留率更高', impact: '多 5 筆／週', selected: true }
    ]
  };
}());
