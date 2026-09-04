# `_is_local()` 只認 localhost／127.0.0.1

Status: before-first-deploy——根治需要「這是不是正式環境」的變數，那顆空白屬 07-2。
關聯：`issue-07-2-settings-sentry-staging-cd.md`。

影響：自架 Supabase 同機的正式拓撲會被判「本機」而放行本機才該放行的東西。
