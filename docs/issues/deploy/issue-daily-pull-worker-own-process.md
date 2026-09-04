# 每日 Meta 花費拉取的 worker 跑在網站行程裡

Status: before-cloud（ADR 0039 明文欠的）。
關聯：`docs/adr/0039`；手動補 `uv run python -m app.meta.daily_pull`。

影響：網站沒開就不拉，那天沒有數字；cron `0 3 * * *` 觸發的時刻仍是機器本地時間。
本機閉環有手動指令頂著，不擋；連續幾天沒開系統回流的數字會缺角。上雲時 worker 要拆成自己的行程。
