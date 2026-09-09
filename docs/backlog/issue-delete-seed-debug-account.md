# 上線前必刪：`supabase/seed.sql` 尾巴的排查用帳號

Status: before-first-deploy（2026-09-02 建，使用者要求）。
關聯：`123@example.com`／`123456`，固定 UUID、固定組織 `org_bughunt`、固定品牌 `brd_bughunt`；`CLAUDE.md` 快速事實那一條。

每次 `supabase db reset` 自動重建，這正是它存在的理由——重置資料庫來查 bug，不會連查 bug 的工具一起炸掉。
`supabase db push` 不會跑 seed 檔，所以它到不了雲端，但它仍是一組進了版控的已知帳密：
**任何一次真的部署之前，這整段連同 CLAUDE.md 那一條一起刪掉。**
