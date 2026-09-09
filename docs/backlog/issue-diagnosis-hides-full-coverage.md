# 判讀面板：花費全部有座標時，「未標座標」那一行整個消失

Status: open（2026-09-09 演練三，Opus 匯總提出；主聊天核實 `DashboardWidgets.tsx:361-370` 只在 `untagged.ad_count > 0` 才畫）。

成因：`frontend/src/components/cockpit/DashboardWidgets.tsx:361-370` 的「未標座標 N 則」是條件渲染；覆蓋率 100% 時沒有任何一行說「全部對上了」。
使用者分不清「真的 0%」與「系統沒算」——演練三的走查者也只能用「兩列受眾合計等於總花費」反推出 0%。

影響：判讀的可信度線索（追蹤覆蓋）在最好的情況下反而不見；純文案與回饋，無資料風險。

做法：route A——覆蓋率 100% 時畫一行 muted 「花費全部對到座標」（design-system §8 用字），其餘不動。
