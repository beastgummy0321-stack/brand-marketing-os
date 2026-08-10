// app/static/pacing_chart.js — 排期曲線圖表渲染（票 pacing-curve）。
// 計畫頁「這期打算怎麼打」與交接包頁「這幾天該花多少」共用同一支函式，資料一律由
// app/ads/pacing_curve.compute_curve() 後端算好（跟 app/ads/pacing.py 的花費步調警示
// 不同支），這裡只讀資料畫圖，不重算金額。依賴 /static/vendor/echarts.min.js
// （docs/redesign-blueprint.md 已選定的圖表庫，vendored 版本，跟 frontend/ 的 npm 依賴
// 是同一支 echarts.min.js，只是複製給尚未搬到 React 的舊版 Jinja 頁面用）。

var PACING_PHASE_COLORS = {
  normal: '#0369a1', warmup: '#7dd3fc', peak: '#0369a1', sprint: '#0c4a6e', reduced: '#bae6fd'
};
var PACING_PHASE_LABELS = {
  normal: '正常量', warmup: '預熱', peak: '高潮', sprint: '衝刺', reduced: '降量'
};

function renderPacingCurveChart(chartId) {
  var dataEl = document.getElementById(chartId + '-data');
  var el = document.getElementById(chartId);
  if (!dataEl || !el || typeof echarts === 'undefined') { return; }
  var days = JSON.parse(dataEl.textContent);
  if (!days.length) { return; }

  var chart = echarts.init(el);
  chart.setOption({
    grid: { left: 48, right: 12, top: 12, bottom: 28 },
    xAxis: {
      type: 'category',
      data: days.map(function (d, i) { return '第' + (i + 1) + '天'; }),
      axisLabel: { interval: Math.max(0, Math.ceil(days.length / 8) - 1) },
    },
    yAxis: { type: 'value' },
    tooltip: {
      trigger: 'axis',
      formatter: function (params) {
        var d = days[params[0].dataIndex];
        var phaseLabel = PACING_PHASE_LABELS[d.phase] || d.phase;
        return '第' + (params[0].dataIndex + 1) + '天・' + phaseLabel
          + '・約 ' + Math.round(d.budget) + ' 元';
      },
    },
    series: [{
      type: 'bar',
      barMaxWidth: 26,
      data: days.map(function (d) {
        return { value: d.budget, itemStyle: { color: PACING_PHASE_COLORS[d.phase] || PACING_PHASE_COLORS.normal } };
      }),
    }],
  });
  window.addEventListener('resize', function () { chart.resize(); });
}
