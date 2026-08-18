/* 唯一假資料進入點：未來串接後端時，只換這個檔案。所有品牌／KOL／媒體名皆虛構。 */

function isoDate(offsetDays) {
  var date = new Date();
  date.setDate(date.getDate() + offsetDays);
  var month = String(date.getMonth() + 1).padStart(2, '0');
  var day = String(date.getDate()).padStart(2, '0');
  return date.getFullYear() + '-' + month + '-' + day;
}

function trackingNodes(statuses) {
  var labels = ['看過', '點進', '填表', '加LINE', '下單'];
  var keys = ['view', 'click', 'form', 'line', 'order'];
  return keys.map(function (key, index) {
    return { key: key, label: labels[index], status: statuses[index] };
  });
}

var TREND_DAYS = ['一', '二', '三', '四', '五', '六', '日'];

function trendData(actual, forecastLow, forecastHigh) {
  return { days: TREND_DAYS, actual: actual, forecastLow: forecastLow, forecastHigh: forecastHigh };
}

function zeroTrend() {
  var zeros = [0, 0, 0, 0, 0, 0, 0];
  return trendData(zeros, zeros, zeros);
}

function byPlatformData(rows) {
  return rows.map(function (row) {
    return { platform: row[0], spend: row[1], orders: row[2], cac: row[3], roas: row[4] };
  });
}

function zeroByPlatform() {
  return byPlatformData([['Meta', 0, 0, 0, 0], ['Google', 0, 0, 0, 0], ['TikTok', 0, 0, 0, 0]]);
}

function perf(spend, orders, cac, roas, goalRate, trend, byPlatform) {
  return { spend: spend, orders: orders, cac: cac, roas: roas, goalRate: goalRate, trend: trend, byPlatform: byPlatform };
}

function zeroPerformance() {
  return perf(0, 0, 0, 0, 0, zeroTrend(), zeroByPlatform());
}

function testRow(name, spend, leads, cac, status) {
  return { name: name, spend: spend, leads: leads, cac: cac, status: status };
}

function testBoard(meta, google, tiktok) {
  return { meta: meta, google: google, tiktok: tiktok };
}

var LEGACY_NAMES = ['固定內容', '再行銷', '會員經營', '節慶活動', '新品推廣'];

function legacyItems(statuses) {
  return LEGACY_NAMES.map(function (name, index) {
    return { name: name, status: statuses[index] };
  });
}

function channelPlan(overrides) {
  var base = [
    { channel: '社群 FB/IG/TikTok', job: '讓陌生人認識' },
    { channel: 'Google 搜尋', job: '接住已在找的人' },
    { channel: 'LINE/Email', job: '把詢問過的人帶回來成交' },
    { channel: 'KOL/媒體/公關/活動', job: '增加信任與話題' },
    { channel: '官網/落地頁', job: '把興趣變成留資料或下單' }
  ];
  return base.map(function (row, index) {
    return { channel: row.channel, job: row.job, pct: overrides[index][0], expected: overrides[index][1] };
  });
}

var mockData = {
  brands: {

    lumibrew: {
      name: '沐光咖啡 LumiBrew',
      stage: 'operating',
      healthLight: 'green',
      monthSummary: { spend: 12500, result: 19 },
      onboardingStep: 4,
      act1: {
        product: {
          desc: '訂閱制精品咖啡豆，依口味喜好每月配送到府',
          price: 'NT$420／包（250g）',
          margin: '毛利約 45%',
          stock: '合作烘豆廠代工，庫存可隨訂閱量彈性調整',
          customers: '約 320 位訂閱戶，多來自社群口碑推薦',
          competitors: ['豆研 BeanLab', '晨霧咖啡 MistBrew'],
          story: '創辦人跑遍南投產地，只挑當季豆做小批次烘焙',
          problem: '新客獲取成本上升，複訂率有待拉高'
        },
        goalType: '直接成交',
        goalNumber: { target: 50, label: '每月新訂閱' },
        budget: { total: 30000, monthlyCap: 30000, maxCacPerLead: 700 },
        personas: {
          batch1: [
            {
              title: '開會前臨時要找伴手禮的人',
              whenNeeded: '臨時要送同事或客戶小禮物時',
              careAbout: '包裝體面、現場好取貨',
              hesitation: '怕對方不喝黑咖啡、怕太貴',
              whereToFind: 'IG 限動、Google 地圖評論'
            },
            {
              title: '週一想給自己一點儀式感的上班族',
              whenNeeded: '每週一早上通勤前',
              careAbout: '風味穩定、沖煮不麻煩',
              hesitation: '訂閱制怕忘記取消、怕喝不完',
              whereToFind: 'Threads、生活風格部落格'
            }
          ],
          batch2: [
            {
              title: '剛開始學手沖的新手',
              whenNeeded: '買了器材想找豆子練習',
              careAbout: '有沖煮教學、豆子好上手',
              hesitation: '怕買錯豆型、怕浪費錢試錯',
              whereToFind: 'YouTube 教學影片留言區'
            },
            {
              title: '想找穩定供應豆源的小型咖啡吧',
              whenNeeded: '店內豆源青黃不接時',
              careAbout: '品質穩定、能配合出貨頻率',
              hesitation: '怕價格比批發貴、怕出貨不準時',
              whereToFind: '咖啡師社團、同業推薦'
            }
          ]
        },
        healthCheck: [
          { channel: '官網', light: 'green', consequence: '頁面速度快，訂閱流程 3 步完成', suggestion: '可加入首月優惠倒數增加急迫感' },
          { channel: 'LINE', light: 'green', consequence: '官方帳號 5 分鐘內自動回覆', suggestion: '旺季建議再備援一位客服' },
          { channel: 'IG', light: 'yellow', consequence: '私訊常隔天才回，詢問度下降', suggestion: '設定自動回覆＋指派專人每日巡查兩次' },
          { channel: '門市', light: 'gray', consequence: '目前無實體門市，此項不適用', suggestion: '—' },
          { channel: '表單', light: 'green', consequence: '表單簡短、跳出率低', suggestion: '可加入生日欄位做後續行銷' }
        ]
      },
      act2: {
        channelPlan: channelPlan([
          [35, '觸及 8–10 萬人次'],
          [25, '20–28 筆高意圖點擊'],
          [15, '喚回 40–60 位舊詢問'],
          [15, '2–3 篇合作曝光'],
          [10, '轉換率提升 1–2 個百分點']
        ]),
        allocation: [
          { platform: 'Meta', pct: 45, amount: 13500 },
          { platform: 'Google', pct: 35, amount: 10500 },
          { platform: 'TikTok', pct: 20, amount: 6000 }
        ],
        predictedRange: { low: 42, high: 58 },
        risk: { level: '中', reasons: ['TikTok 新素材尚無成效數據', '訂閱商品需先累積再行銷受眾', 'Google 關鍵字競價在週末偏高'] },
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
        tracking: { nodes: trackingNodes(['done', 'done', 'done', 'done', 'done']) },
        riskControls: { dailyCap: 1200, autoPauseThreshold: 8 },
        schedule: { start: isoDate(-14), end: isoDate(16) },
        approved: true
      },
      act3: {
        testBoard: {
          before: {
            meta: [
              { name: '主視覺 A：週一儀式感', spend: 2600, leads: 6, cac: 433, status: '測試中' },
              { name: '主視覺 B：開箱畫面', spend: 1900, leads: 2, cac: 950, status: '測試中' }
            ],
            google: [
              { name: '搜尋文案｜咖啡豆訂閱', spend: 2400, leads: 5, cac: 480, status: '測試中' },
              { name: '搜尋文案｜精品配送', spend: 2100, leads: 4, cac: 525, status: '測試中' }
            ],
            tiktok: [
              { name: '短影音 A：手沖特寫', spend: 1400, leads: 1, cac: 1400, status: '測試中' },
              { name: '短影音 B：風味卡對照', spend: 1000, leads: 1, cac: 1000, status: '測試中' }
            ]
          },
          after: {
            meta: [
              { name: '主視覺 A：週一儀式感', spend: 3400, leads: 15, cac: 227, status: '加碼中' },
              { name: '主視覺 B：開箱畫面', spend: 0, leads: 0, cac: 0, status: '已停' }
            ],
            google: [
              { name: '搜尋文案｜咖啡豆訂閱', spend: 3600, leads: 19, cac: 189, status: '加碼中' },
              { name: '搜尋文案｜精品配送', spend: 2100, leads: 10, cac: 210, status: '測試中' }
            ],
            tiktok: [
              { name: '短影音 A：手沖特寫', spend: 1300, leads: 3, cac: 433, status: '測試中' },
              { name: '短影音 B：風味卡對照', spend: 0, leads: 0, cac: 0, status: '已停' }
            ]
          }
        },
        weeklyProposals: [
          { action: '停掉', target: 'Meta 主視覺 B：開箱畫面', reason: '連續五筆花費沒有詢問轉單', impact: '省 NT$1,900／週', selected: true },
          { action: '加碼', target: 'Google 搜尋文案｜咖啡豆訂閱', reason: '高意圖搜尋成本最低', impact: '多 13 筆／週', selected: true },
          { action: '換素材', target: 'TikTok 短影音 B', reason: '完播率低於平台平均一半', impact: '多 2 筆／週', selected: true }
        ],
        legacy: legacyItems(['built', 'built', 'suggest', 'built', 'suggest']),
        todo3: { productCompleteness: 82, replySpeed: 'yellow', goodCustomerDefined: false },
        kolTasks: [
          { who: '生活選物帳號｜阿栗生活誌', topic: '一週咖啡儀式感開箱', expectedEffect: '預期觸及 3–5 萬、帶 15–20 筆詢問', status: '已接洽' },
          { who: '咖啡愛好者社團版主｜豆香誌', topic: '產地故事＋試飲心得', expectedEffect: '建立產地信任感，長期複訂率提升', status: '未接洽' },
          { who: '職人選物 Podcast｜慢作坊', topic: '創辦人訪談＋聽眾專屬折扣', expectedEffect: '預期帶來 8–12 筆高忠誠度訂閱', status: '已合作' }
        ],
        performance: {
          before: {
            spend: 12500, orders: 19, cac: 658, roas: 1.62, goalRate: 38,
            trend: {
              days: ['一', '二', '三', '四', '五', '六', '日'],
              actual: [2, 3, 4, 5, 5, 7, 8],
              forecastLow: [2, 3, 3, 4, 5, 5, 6],
              forecastHigh: [4, 5, 7, 8, 10, 12, 14]
            },
            byPlatform: [
              { platform: 'Meta', spend: 5600, orders: 8, cac: 700, roas: 1.42 },
              { platform: 'Google', spend: 4500, orders: 9, cac: 500, roas: 2.12 },
              { platform: 'TikTok', spend: 2400, orders: 2, cac: 1200, roas: 0.74 }
            ]
          },
          after: {
            spend: 12100, orders: 47, cac: 257, roas: 3.08, goalRate: 94,
            trend: {
              days: ['一', '二', '三', '四', '五', '六', '日'],
              actual: [5, 12, 18, 25, 32, 40, 47],
              forecastLow: [4, 9, 15, 21, 27, 34, 41],
              forecastHigh: [7, 15, 23, 31, 39, 47, 55]
            },
            byPlatform: [
              { platform: 'Meta', spend: 3400, orders: 15, cac: 227, roas: 2.94 },
              { platform: 'Google', spend: 5700, orders: 29, cac: 197, roas: 4.01 },
              { platform: 'TikTok', spend: 3000, orders: 3, cac: 1000, roas: 0.92 }
            ]
          }
        }
      }
    },

    misttea: {
      name: '山霧茶事 MistTea',
      stage: 'proposal',
      healthLight: 'yellow',
      monthSummary: { spend: 0, result: 0 },
      onboardingStep: 4,
      act1: {
        product: {
          desc: '手採高山烏龍茶禮盒，主打送禮與居家沖泡兩用',
          price: 'NT$1,280／盒（4 兩裝）',
          margin: '毛利約 52%',
          stock: '產季限量，每季約 600 盒，售完需等下季',
          customers: '目前多為熟客電話訂購，年輕客群薄弱',
          competitors: ['豆研 BeanLab', '晨霧咖啡 MistBrew'],
          story: '三代茶農在梨山海拔 1600 公尺自種自製，堅持手採不機採',
          problem: '不會經營社群，詢問常常轉不成訂單'
        },
        goalType: '更多私訊',
        goalNumber: { target: 150, label: '每月有效詢問' },
        budget: { total: 18000, monthlyCap: 18000, maxCacPerLead: 90 },
        personas: {
          batch1: [
            {
              title: '中秋前找體面伴手禮的人',
              whenNeeded: '節慶前兩週開始比較茶禮盒',
              careAbout: '包裝有質感、送長輩不失禮',
              hesitation: '怕價格偏高、怕對方喝不出差異',
              whereToFind: 'FB 社團、LINE 熟人推薦'
            },
            {
              title: '想在家泡出一杯像樣烏龍的人',
              whenNeeded: '假日在家想放鬆泡茶時',
              careAbout: '茶葉來源清楚、附沖泡教學',
              hesitation: '不會挑茶、怕買到混茶',
              whereToFind: 'IG 生活風格帳號、小紅書'
            }
          ],
          batch2: [
            {
              title: '幫公司採購中秋禮盒的窗口',
              whenNeeded: '中元、中秋前批量採購時',
              careAbout: '可開發票、大量訂購有優惠',
              hesitation: '怕交期趕不上、怕品質不一',
              whereToFind: 'Google 搜尋「中秋禮盒批發」'
            },
            {
              title: '茶藝入門想找穩定茶源的人',
              whenNeeded: '上完茶藝課想自己練習沖泡',
              careAbout: '茶種說明清楚、能小量試喝',
              hesitation: '怕買了不合口味、怕過度包裝',
              whereToFind: '茶藝社團、Threads'
            }
          ]
        },
        healthCheck: [
          { channel: '官網', light: 'yellow', consequence: '手機版結帳流程要跳三頁，容易放棄', suggestion: '簡化成一頁式結帳並加入信任標章' },
          { channel: 'LINE', light: 'red', consequence: '常常超過一天才回，詢問直接轉去問別家', suggestion: '設定自動回覆並排定每日固定回覆時段' },
          { channel: 'IG', light: 'yellow', consequence: '貼文更新不穩定，私訊回覆偏慢', suggestion: '排定每週兩則固定貼文並開自動回覆' },
          { channel: '門市', light: 'gray', consequence: '僅產地小攤位，非常態門市', suggestion: '—' },
          { channel: '表單', light: 'green', consequence: '團購表單簡單好填', suggestion: '可加入送禮對象欄位方便客製' }
        ]
      },
      act2: {
        channelPlan: channelPlan([
          [30, '觸及 4–6 萬人次'],
          [20, '12–18 筆高意圖點擊'],
          [25, '喚回 30–40 位舊詢問'],
          [15, '1–2 篇合作曝光'],
          [10, '轉換率提升 1 個百分點']
        ]),
        allocation: [
          { platform: 'Meta', pct: 55, amount: 9900 },
          { platform: 'Google', pct: 20, amount: 3600 },
          { platform: 'TikTok', pct: 25, amount: 4500 }
        ],
        predictedRange: { low: 90, high: 130 },
        risk: { level: '中', reasons: ['產季限量，旺季詢問可能超過供貨量', 'LINE 回覆速度未改善前轉換會流失', '中秋檔期同業競價會墊高單次點擊成本'] },
        creatives: {
          meta: {
            batch1: [
              { title: '送長輩，送這盒剛剛好', body: '梨山手採烏龍，中秋禮盒現貨開放預訂。', color: '#E3E0CF' },
              { title: '一泡就懂什麼叫高山氣', body: '三代茶農親手採製，附沖泡教學卡。', color: '#D8E3D4' }
            ],
            batch2: [
              { title: '這個中秋，換一份有故事的禮', body: '海拔 1600 公尺，堅持手採不機採。', color: '#EAD9CE' },
              { title: '在家也能泡出茶行等級', body: '禮盒附三種沖泡法教學，新手也上手。', color: '#DCE0EA' }
            ]
          },
          google: {
            batch1: [
              { headline1: '中秋茶禮盒｜山霧茶事', headline2: '梨山手採高山烏龍', description: '三代茶農自種自製，送禮自用兩相宜。' },
              { headline1: '高山烏龍禮盒推薦', headline2: '產地直送新鮮現焙', description: '限量產季供應，附沖泡教學卡。' }
            ],
            batch2: [
              { headline1: '團購禮盒｜山霧茶事', headline2: '公司採購可開發票', description: '大量訂購享優惠，交期提前預約有保障。' },
              { headline1: '烏龍茶葉推薦', headline2: '手採不機採更香醇', description: '梨山高山茶區直送，小量試喝方案可選。' }
            ]
          },
          tiktok: {
            batch1: [
              { color: '#E5E1CE', points: ['0–3 秒：茶園手採畫面', '4–8 秒：炒菁與揉捻特寫', '9–13 秒：一句「三代人的堅持」'] },
              { color: '#D9E3D5', points: ['0–2 秒：拆開禮盒瞬間', '3–7 秒：熱水注入茶壺冒煙', '8–12 秒：展示中秋預購連結'] }
            ],
            batch2: [
              { color: '#EAD9CE', points: ['0–3 秒：茶農在雲霧中採茶', '4–9 秒：沖泡教學三步驟', '10–13 秒：一句「送禮先送懂茶的心」'] },
              { color: '#D9DFE9', points: ['0–2 秒：辦公室拆團購箱', '3–8 秒：同事試喝反應', '9–12 秒：展示團購優惠碼'] }
            ]
          }
        },
        tracking: { nodes: trackingNodes(['done', 'done', 'checking', 'pending', 'pending']) },
        riskControls: { dailyCap: 900, autoPauseThreshold: 6 },
        schedule: { start: isoDate(0), end: isoDate(30) },
        approved: false
      },
      act3: {
        testBoard: {
          before: {
            meta: [
              { name: '送長輩，送這盒剛剛好', spend: 0, leads: 0, cac: 0, status: '測試中' },
              { name: '一泡就懂什麼叫高山氣', spend: 0, leads: 0, cac: 0, status: '測試中' }
            ],
            google: [
              { name: '中秋茶禮盒｜山霧茶事', spend: 0, leads: 0, cac: 0, status: '測試中' },
              { name: '高山烏龍禮盒推薦', spend: 0, leads: 0, cac: 0, status: '測試中' }
            ],
            tiktok: [
              { name: '茶園手採畫面', spend: 0, leads: 0, cac: 0, status: '測試中' },
              { name: '拆開禮盒瞬間', spend: 0, leads: 0, cac: 0, status: '測試中' }
            ]
          },
          after: {
            meta: [
              { name: '送長輩，送這盒剛剛好', spend: 3200, leads: 22, cac: 145, status: '加碼中' },
              { name: '一泡就懂什麼叫高山氣', spend: 0, leads: 0, cac: 0, status: '已停' }
            ],
            google: [
              { name: '中秋茶禮盒｜山霧茶事', spend: 2600, leads: 19, cac: 137, status: '加碼中' },
              { name: '高山烏龍禮盒推薦', spend: 1000, leads: 6, cac: 167, status: '測試中' }
            ],
            tiktok: [
              { name: '茶園手採畫面', spend: 1400, leads: 5, cac: 280, status: '測試中' },
              { name: '拆開禮盒瞬間', spend: 0, leads: 0, cac: 0, status: '已停' }
            ]
          }
        },
        weeklyProposals: [
          { action: '停掉', target: 'Meta「一泡就懂什麼叫高山氣」', reason: '點擊率明顯低於同組另一則', impact: '省 NT$700／週', selected: true },
          { action: '加碼', target: 'Meta「送長輩，送這盒剛剛好」', reason: '單筆詢問成本最低', impact: '多 12 筆／週', selected: true },
          { action: '換素材', target: 'TikTok「拆開禮盒瞬間」', reason: '完播率偏低，畫面節奏太慢', impact: '多 3 筆／週', selected: true }
        ],
        legacy: legacyItems(['suggest', 'suggest', 'suggest', 'suggest', 'suggest']),
        todo3: { productCompleteness: 64, replySpeed: 'yellow', goodCustomerDefined: false },
        kolTasks: [
          { who: '茶生活選物帳號｜茶山日記', topic: '中秋禮盒開箱＋沖泡示範', expectedEffect: '預期觸及 2–4 萬、帶 10–15 筆詢問', status: '未接洽' },
          { who: '在地媒體｜梨山小報', topic: '三代茶農故事專訪', expectedEffect: '建立產地信任感，提升客單價', status: '未接洽' }
        ],
        performance: {
          before: zeroPerformance(),
          after: perf(
            8200, 52, 158, 2.4, 35,
            trendData([5, 12, 20, 28, 36, 44, 52], [4, 9, 16, 23, 30, 38, 45], [7, 15, 24, 32, 41, 50, 58]),
            byPlatformData([['Meta', 3200, 22, 145, 2.6], ['Google', 3600, 25, 144, 2.5], ['TikTok', 1400, 5, 280, 1.1]])
          )
        }
      }
    },

    sunbook: {
      name: '日青文具 Sunbook',
      stage: 'onboarding',
      healthLight: 'gray',
      monthSummary: { spend: 0, result: 0 },
      onboardingStep: 2,
      act1: {
        product: {
          desc: '日系文青風文具與筆記本，主打實體門市體驗與客製刻字',
          price: '筆記本 NT$280 起、客製刻字加購 NT$100',
          margin: '毛利約 38%',
          stock: '門市備貨為主，熱門款常缺貨',
          customers: '學生與文具愛好者，多為門市路過客',
          competitors: ['豆研 BeanLab', '晨霧咖啡 MistBrew'],
          story: '老闆從日本選品進口起家，兩年前開了第一家實體門市',
          problem: '線上曝光少，很多人不知道門市在哪'
        },
        goalType: '更多到店',
        goalNumber: { target: 400, label: '每月到店人次' },
        budget: { total: 12000, monthlyCap: 12000, maxCacPerLead: 25 },
        personas: {
          batch1: [
            {
              title: '開學前補文具的學生',
              whenNeeded: '開學前兩週逛街採買',
              careAbout: '款式好看、價格能接受',
              hesitation: '怕線上看到的到店缺貨',
              whereToFind: 'IG 限動、學校附近社團'
            },
            {
              title: '想客製禮物送朋友的人',
              whenNeeded: '生日或畢業季前找特別的禮物',
              careAbout: '可以刻字、獨一無二',
              hesitation: '不確定門市在哪、營業時間',
              whereToFind: 'Google 地圖、小紅書'
            }
          ],
          batch2: [
            {
              title: '文具收藏愛好者',
              whenNeeded: '看到新品上架時',
              careAbout: '限量款、日本直送',
              hesitation: '怕到店撲空、想先確認庫存',
              whereToFind: 'IG 文具社群、Threads'
            },
            {
              title: '路過想順便逛逛的人',
              whenNeeded: '在附近商圈閒晃時',
              careAbout: '門口好認、櫥窗吸引人',
              hesitation: '不知道這是文具店還是咖啡店',
              whereToFind: 'Google 地圖評論、街景'
            }
          ]
        },
        healthCheck: [
          { channel: '官網', light: 'yellow', consequence: '只有簡易介紹頁，沒有庫存查詢', suggestion: '加入即時庫存或到店預留功能' },
          { channel: 'LINE', light: 'green', consequence: '門市人員即時回覆詢問', suggestion: '可加開自動回覆營業時間' },
          { channel: 'IG', light: 'yellow', consequence: '貼文頻率不穩，新品常沒公告', suggestion: '固定每週兩則新品／到貨公告' },
          { channel: '門市', light: 'green', consequence: '店內動線清楚，服務評價高', suggestion: '可加裝清楚的招牌指引' },
          { channel: '表單', light: 'gray', consequence: '目前無線上預約或表單', suggestion: '—' }
        ]
      },
      act2: {
        channelPlan: channelPlan([
          [45, '觸及 3–5 萬人次'],
          [10, '5–8 筆高意圖點擊'],
          [10, '喚回 15–20 位舊詢問'],
          [15, '1 篇合作曝光'],
          [20, '轉換率提升 1 個百分點']
        ]),
        allocation: [
          { platform: 'Meta', pct: 55, amount: 6600 },
          { platform: 'Google', pct: 15, amount: 1800 },
          { platform: 'TikTok', pct: 30, amount: 3600 }
        ],
        predictedRange: { low: 320, high: 460 },
        risk: { level: '低', reasons: ['商圈流量穩定波動不大', '熱門款缺貨可能讓到店客失望', '尚無到店預留機制承接線上詢問'] },
        creatives: {
          meta: {
            batch1: [
              { title: '刻上名字，這份禮物只有你有', body: '日系文具＋現場刻字，門市週週有新品。', color: '#EFE3D0' },
              { title: '開學文具一次補齊', body: '人氣款到貨中，快來門市挑選。', color: '#D9E6E4' }
            ],
            batch2: [
              { title: '路過別錯過，櫥窗新品上架', body: '日本直送限量款，數量有限。', color: '#E6DCEF' },
              { title: '送禮不知道選什麼？來門市看看', body: '現場刻字服務，當天就能拿。', color: '#EAD9CE' }
            ]
          },
          google: {
            batch1: [
              { headline1: '日系文具門市｜日青文具', headline2: '現場客製刻字服務', description: '日本直送筆記本與文具，門市即買即拿。' },
              { headline1: '客製刻字禮物推薦', headline2: '當天完成不用等', description: '生日畢業季首選，獨一無二的小禮物。' }
            ],
            batch2: [
              { headline1: '文具控必逛｜日青文具', headline2: '限量新品每週上架', description: '日本選品直送，門市貨況即時掌握。' },
              { headline1: '開學文具採購', headline2: '款式齊全價格實在', description: '學生優惠不定期推出，門市現場選購。' }
            ]
          },
          tiktok: {
            batch1: [
              { color: '#EFE3D0', points: ['0–3 秒：刻字機現場作業', '4–8 秒：完成品特寫', '9–12 秒：展示門市地址字卡'] },
              { color: '#D9E6E4', points: ['0–2 秒：新品開箱瞬間', '3–7 秒：陳列牆特寫', '8–11 秒：一句「本週新品到囉」'] }
            ],
            batch2: [
              { color: '#E6DCEF', points: ['0–3 秒：顧客挑選文具畫面', '4–8 秒：結帳打包過程', '9–12 秒：展示營業時間字卡'] },
              { color: '#EAD9CE', points: ['0–2 秒：門口櫥窗全景', '3–7 秒：走進店內動線', '8–11 秒：一句「路過就進來看看」'] }
            ]
          }
        },
        tracking: { nodes: trackingNodes(['pending', 'pending', 'pending', 'pending', 'pending']) },
        riskControls: { dailyCap: 500, autoPauseThreshold: 10 },
        schedule: { start: isoDate(0), end: isoDate(30) },
        approved: false
      },
      act3: {
        testBoard: {
          before: {
            meta: [
              testRow('刻上名字，這份禮物只有你有', 0, 0, 0, '測試中'),
              testRow('開學文具一次補齊', 0, 0, 0, '測試中')
            ],
            google: [
              testRow('日系文具門市｜日青文具', 0, 0, 0, '測試中'),
              testRow('客製刻字禮物推薦', 0, 0, 0, '測試中')
            ],
            tiktok: [
              testRow('刻字機現場作業', 0, 0, 0, '測試中'),
              testRow('新品開箱瞬間', 0, 0, 0, '測試中')
            ]
          },
          after: {
            meta: [
              testRow('刻上名字，這份禮物只有你有', 2600, 118, 22, '加碼中'),
              testRow('開學文具一次補齊', 900, 30, 30, '測試中')
            ],
            google: [
              testRow('日系文具門市｜日青文具', 700, 22, 32, '測試中'),
              testRow('客製刻字禮物推薦', 0, 0, 0, '已停')
            ],
            tiktok: [
              testRow('刻字機現場作業', 1800, 95, 19, '加碼中'),
              testRow('新品開箱瞬間', 0, 0, 0, '已停')
            ]
          }
        },
        weeklyProposals: [
          { action: '停掉', target: 'Google「客製刻字禮物推薦」', reason: '搜尋量太低，點擊成本偏高', impact: '省 NT$400／週', selected: true },
          { action: '加碼', target: 'TikTok「刻字機現場作業」', reason: '到店詢問轉換最高', impact: '多 60 人次／週', selected: true },
          { action: '換素材', target: 'Meta「開學文具一次補齊」', reason: '素材已使用兩週，成效趨緩', impact: '多 15 人次／週', selected: true }
        ],
        legacy: legacyItems(['suggest', 'suggest', 'suggest', 'suggest', 'suggest']),
        todo3: { productCompleteness: 45, replySpeed: 'green', goodCustomerDefined: false },
        kolTasks: [
          { who: '在地生活誌｜巷口有事', topic: '門市探店＋刻字體驗', expectedEffect: '預期帶來 40–60 人次到店', status: '未接洽' }
        ],
        performance: {
          before: zeroPerformance(),
          after: perf(
            6000, 265, 23, 4.4, 66,
            trendData([30, 68, 105, 150, 195, 232, 265], [22, 55, 90, 128, 168, 205, 238], [38, 82, 128, 178, 228, 270, 305]),
            byPlatformData([['Meta', 3500, 148, 24, 4.1], ['Google', 700, 22, 32, 3.2], ['TikTok', 1800, 95, 19, 5.6]])
          )
        }
      }
    }
  },

  draftBrandTemplate: {
    name: '新品牌（示範）',
    stage: 'onboarding',
    healthLight: 'gray',
    monthSummary: { spend: 0, result: 0 },
    onboardingStep: 1,
    act1: {
      product: {
        desc: 'AI 已分析網址，這裡先填入示範內容，請逐欄確認或修改',
        price: 'NT$0（請填入實際定價）',
        margin: '毛利約 40%（AI 推估）',
        stock: '請填入目前庫存狀況',
        customers: '請填入目前主要客源',
        competitors: ['豆研 BeanLab', '晨霧咖啡 MistBrew'],
        story: '請填入一句話品牌故事',
        problem: '請填入目前遇到的問題'
      },
      goalType: '更多人認識',
      goalNumber: { target: 100, label: '每月目標' },
      budget: { total: 15000, monthlyCap: 15000, maxCacPerLead: 100 },
      personas: {
        batch1: [
          { title: '示範情境卡一', whenNeeded: '請填入何時需要', careAbout: '請填入在意什麼', hesitation: '請填入為何猶豫', whereToFind: '請填入在哪看資訊' },
          { title: '示範情境卡二', whenNeeded: '請填入何時需要', careAbout: '請填入在意什麼', hesitation: '請填入為何猶豫', whereToFind: '請填入在哪看資訊' }
        ],
        batch2: [
          { title: '示範情境卡三', whenNeeded: '請填入何時需要', careAbout: '請填入在意什麼', hesitation: '請填入為何猶豫', whereToFind: '請填入在哪看資訊' },
          { title: '示範情境卡四', whenNeeded: '請填入何時需要', careAbout: '請填入在意什麼', hesitation: '請填入為何猶豫', whereToFind: '請填入在哪看資訊' }
        ]
      },
      healthCheck: [
        { channel: '官網', light: 'green', consequence: 'AI 已檢查：頁面速度正常，跳出率不高', suggestion: '可加入首購優惠倒數增加急迫感' },
        { channel: 'LINE', light: 'yellow', consequence: 'AI 已檢查：回覆常超過半天，帶來的詢問會流失', suggestion: '設定自動回覆＋指派專人每日巡查兩次' },
        { channel: 'IG', light: 'red', consequence: 'AI 已檢查：私訊常兩天以上才回，等於把廣告預算丟進海裡', suggestion: '立即開啟自動回覆，並排定每日至少兩次巡查時段' },
        { channel: '門市', light: 'gray', consequence: 'AI 已檢查：目前無實體門市，此項不適用', suggestion: '—' },
        { channel: '表單', light: 'green', consequence: 'AI 已檢查：表單簡短、填寫完成率高', suggestion: '可加入生日欄位做後續行銷' }
      ]
    },
    act2: {
      channelPlan: channelPlan([[35, '觸及待估'], [25, '點擊待估'], [15, '喚回待估'], [15, '曝光待估'], [10, '轉換待估']]),
      allocation: [
        { platform: 'Meta', pct: 40, amount: 6000 },
        { platform: 'Google', pct: 30, amount: 4500 },
        { platform: 'TikTok', pct: 30, amount: 4500 }
      ],
      predictedRange: { low: 0, high: 0 },
      risk: { level: '中', reasons: ['尚無歷史數據可參考', '受眾輪廓需要投放後驗證', '素材成效尚未經市場測試'] },
      creatives: {
        meta: {
          batch1: [
            { title: '示範文案一', body: '示範內文，請依實際素材替換。', color: '#E2E8F0' },
            { title: '示範文案二', body: '示範內文，請依實際素材替換。', color: '#E2E8F0' }
          ],
          batch2: [
            { title: '示範文案三', body: '示範內文，請依實際素材替換。', color: '#E2E8F0' },
            { title: '示範文案四', body: '示範內文，請依實際素材替換。', color: '#E2E8F0' }
          ]
        },
        google: {
          batch1: [
            { headline1: '示範標題一', headline2: '示範副標一', description: '示範文案，請依實際內容替換。' },
            { headline1: '示範標題二', headline2: '示範副標二', description: '示範文案，請依實際內容替換。' }
          ],
          batch2: [
            { headline1: '示範標題三', headline2: '示範副標三', description: '示範文案，請依實際內容替換。' },
            { headline1: '示範標題四', headline2: '示範副標四', description: '示範文案，請依實際內容替換。' }
          ]
        },
        tiktok: {
          batch1: [
            { color: '#CBD5E1', points: ['0–3 秒：示範腳本一', '4–8 秒：示範腳本二', '9–12 秒：示範腳本三'] },
            { color: '#CBD5E1', points: ['0–3 秒：示範腳本一', '4–8 秒：示範腳本二', '9–12 秒：示範腳本三'] }
          ],
          batch2: [
            { color: '#CBD5E1', points: ['0–3 秒：示範腳本四', '4–8 秒：示範腳本五', '9–12 秒：示範腳本六'] },
            { color: '#CBD5E1', points: ['0–3 秒：示範腳本四', '4–8 秒：示範腳本五', '9–12 秒：示範腳本六'] }
          ]
        }
      },
      tracking: { nodes: trackingNodes(['pending', 'pending', 'pending', 'pending', 'pending']) },
      riskControls: { dailyCap: 500, autoPauseThreshold: 5 },
      schedule: { start: isoDate(0), end: isoDate(30) },
      approved: false
    },
    act3: {
      testBoard: {
        before: testBoard(
          [testRow('示範素材一', 0, 0, 0, '測試中')],
          [testRow('示範素材二', 0, 0, 0, '測試中')],
          [testRow('示範素材三', 0, 0, 0, '測試中')]
        ),
        after: testBoard(
          [testRow('示範素材一', 0, 0, 0, '測試中')],
          [testRow('示範素材二', 0, 0, 0, '測試中')],
          [testRow('示範素材三', 0, 0, 0, '測試中')]
        )
      },
      weeklyProposals: [
        { action: '停掉', target: '示範對象一', reason: '示範理由，尚無實際數據', impact: '示範預期影響', selected: true },
        { action: '加碼', target: '示範對象二', reason: '示範理由，尚無實際數據', impact: '示範預期影響', selected: true },
        { action: '換素材', target: '示範對象三', reason: '示範理由，尚無實際數據', impact: '示範預期影響', selected: true }
      ],
      legacy: legacyItems(['suggest', 'suggest', 'suggest', 'suggest', 'suggest']),
      todo3: { productCompleteness: 0, replySpeed: 'yellow', goodCustomerDefined: false },
      kolTasks: [{ who: '待建議', topic: '待建議', expectedEffect: '待建議', status: '未接洽' }],
      performance: {
        before: zeroPerformance(),
        after: zeroPerformance()
      }
    }
  }
};

window.mockData = mockData;
