"""app/ads — 廣告分支（路線圖分支 1）：開期 → 計畫 → 素材 → 交接包 → 成效 → 判讀 → 下期草案。

共識與拆票見 docs/decisions/0022；資料表見 migrations/0001_tables.sql
（設計來源 docs/design/03-data-model.md §4、§5）。

模組切分：03 §8 的五個概念模組（Campaign Planning／Creative Studio／Publishing Handoff／
Performance Analytics／Experimentation）在實作上合併為本模組，理由見 migrations 檔頭。
"""
