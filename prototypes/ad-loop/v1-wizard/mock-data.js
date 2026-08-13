/* PROTOTYPE DATA ONLY: 未來接真實資料時，僅替換此檔。 */
window.AD_LOOP_DATA = {
  brand: '沐光咖啡 LumiBrew',
  productUrl: 'lumibrew.example.com',
  accounts: [
    { id: 'meta', platform: 'meta', label: 'Meta', status: 'idle' },
    { id: 'google', platform: 'google', label: 'Google', status: 'idle' },
    { id: 'tiktok', platform: 'tiktok', label: 'TikTok', status: 'idle' }
  ],
  tracking: { url: 'lumibrew.example.com', status: 'idle' },
  productAnalysisSets: [
    {
      sellingPoints: ['每週新鮮烘焙', '訂閱免運', '風味自由選'],
      audiences: ['25–39 歲上班族', '在家手沖愛好者'],
      competitors: ['豆研 BeanLab', '晨霧咖啡 MistBrew']
    },
    {
      sellingPoints: ['產地批次透明', '首月體驗價', '沖煮指南隨箱附'],
      audiences: ['重視產地的咖啡客', '送禮採購族群'],
      competitors: ['豆研 BeanLab', '晨霧咖啡 MistBrew']
    }
  ],
  strategy: {
    budgetTotal: 30000,
    split: { meta: 40, google: 35, tiktok: 25 },
    goal: '線上訂閱訂單',
    estimate: { ordersLow: 45, ordersHigh: 60, cpaLow: 500, cpaHigh: 650 }
  },
  strategyAlternate: {
    budgetTotal: 30000,
    split: { meta: 35, google: 40, tiktok: 25 },
    goal: '線上訂閱訂單',
    estimate: { ordersLow: 48, ordersHigh: 62, cpaLow: 485, cpaHigh: 625 }
  },
  creatives: {
    meta: {
      batchA: [
        { title: '早晨，從一杯剛烘好的咖啡開始', body: '每週新鮮烘焙，風味照你的習慣配。訂閱後直接送到家。', cta: '立即訂閱' },
        { title: '把挑豆這件事交給我們', body: '三分鐘選好風味，之後每週都有一包好咖啡等你。', cta: '查看方案' }
      ],
      batchB: [
        { title: '首月訂閱，從喜歡的風味開始', body: '花果、堅果、可可三種路線，這週烘好就寄出。', cta: '挑選風味' },
        { title: '手沖新手也能喝懂產地', body: '每包附沖煮卡，今天打開就能沖出穩定的一杯。', cta: '開始體驗' }
      ]
    },
    google: {
      batchA: [
        { headline1: '咖啡豆訂閱｜每週新鮮烘焙', headline2: '選好風味，直接送到家', displayUrl: 'lumibrew.example.com/subscribe', description: '首月體驗方案，免去每週挑豆的麻煩。' },
        { headline1: '手沖咖啡豆推薦', headline2: '產地風味自由選', displayUrl: 'lumibrew.example.com/beans', description: '從淺焙花香到深焙可可，找到今天想喝的味道。' }
      ],
      batchB: [
        { headline1: '新鮮烘焙咖啡豆訂閱', headline2: '每週送達，首月體驗價', displayUrl: 'lumibrew.example.com/start', description: '下單後才排烘焙，訂閱每週都有新鮮的一杯。' },
        { headline1: '咖啡豆怎麼選？', headline2: '三步找到你的風味', displayUrl: 'lumibrew.example.com/guide', description: '用簡單風味問答，配出適合你的手沖咖啡豆。' }
      ]
    },
    tiktok: {
      batchA: [
        { coverLabel: '一週咖啡開箱', script: ['打開本週烘焙包', '30 秒認識產地風味', '沖出第一杯的香氣'], duration: '15 秒' },
        { coverLabel: '手沖新手第一包', script: ['挑選今天的焙度', '照沖煮卡注水', '一口喝出差別'], duration: '15 秒' }
      ],
      batchB: [
        { coverLabel: '咖啡豆到家的一天', script: ['包裹抵達餐桌', '拆開看本週風味', '早晨手沖實拍'], duration: '15 秒' },
        { coverLabel: '三種風味盲測', script: ['花香、堅果、可可排開', '第一口反應', '選出下週訂閱'], duration: '15 秒' }
      ]
    }
  },
  launchDefaults: {
    dailyCap: 1000,
    dailyCapMin: 300,
    dailyCapMax: 3000,
    dailyCapStep: 100,
    pauseThresholdDays: 3,
    pauseThresholdOptions: [1, 3, 5],
    scheduleStart: '2026/08/13',
    scheduleEnd: '2026/09/11',
    scheduleDays: 30
  },
  dashboardBefore: {
    spend: 12500,
    orders: 22,
    cpa: 568,
    roas: 2.3,
    trend7d: [
      { day: '週一', spend: 1500, orders: 2 }, { day: '週二', spend: 1650, orders: 3 },
      { day: '週三', spend: 1720, orders: 3 }, { day: '週四', spend: 1800, orders: 3 },
      { day: '週五', spend: 1950, orders: 4 }, { day: '週六', spend: 2030, orders: 3 },
      { day: '週日', spend: 1850, orders: 4 }
    ],
    platforms: [
      { name: 'Meta', spend: 5200, orders: 9, cpa: 578, roas: 2.1 },
      { name: 'Google', spend: 4300, orders: 8, cpa: 538, roas: 2.6 },
      { name: 'TikTok', spend: 3000, orders: 5, cpa: 600, roas: 1.9 }
    ]
  },
  dashboardAfter: {
    spend: 12500,
    orders: 31,
    cpa: 403,
    roas: 3.2,
    comparisons: {
      spend: '● 花費不變',
      orders: '▲ 多 9 筆訂單',
      cpa: '▲ 每筆成本↓29%',
      roas: '▲ ROAS↑0.9'
    },
    trend7d: [
      { day: '週一', spend: 1500, orders: 3 }, { day: '週二', spend: 1650, orders: 4 },
      { day: '週三', spend: 1720, orders: 4 }, { day: '週四', spend: 1800, orders: 5 },
      { day: '週五', spend: 1950, orders: 5 }, { day: '週六', spend: 2030, orders: 5 },
      { day: '週日', spend: 1850, orders: 5 }
    ],
    platforms: [
      { name: 'Meta', spend: 4300, orders: 11, cpa: 391, roas: 3.1 },
      { name: 'Google', spend: 5200, orders: 14, cpa: 371, roas: 3.7 },
      { name: 'TikTok', spend: 3000, orders: 6, cpa: 500, roas: 2.5 }
    ]
  },
  suggestions: [
    { id: 'pause', type: 'pause', title: '暫停：Meta／甜點系列廣告', reason: '連續 5 天無轉換', impact: '預期每月省下 NT$1,800', defaultChecked: true },
    { id: 'boost', type: 'boost', title: '加碼：Google／搜尋廣告', reason: '每筆成本比平均低 32%', impact: '預期多帶 6–8 筆訂單', defaultChecked: true },
    { id: 'swap', type: 'swap', title: '換素材：TikTok／開箱腳本', reason: '完播率低於門檻', impact: '預期完播率提升 20%', defaultChecked: false }
  ]
};
