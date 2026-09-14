# 策略頁數字條在 1024 寬擠成直條

Status: 2026-09-14 F06-I02 審查時看到（不屬於該票）。

事實：策略分頁的 `KpiStrip`（五格：平台／預算／配置／時間／需要素材）在 1024 寬時「配置」那格的
「新客 50% / 再行銷 30% / 探索 20%」擠成三行直條，「需要素材」也折行。1920 寬正常。
截圖：`C:\Users\User\AppData\Local\Temp\harness-shots\F06-I02\strategy-1024.png`（暫存，會被清）。

待查：`frontend/src/components/ads/patterns/KpiStrip.tsx` 的格寬規則；是五格固定等寬，還是配置那格的字串太長。
`docs/design-system.md` §9/§10 要求 1024 寬驗收。
