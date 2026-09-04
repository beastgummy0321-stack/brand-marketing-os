# 邀請連結是「持有即可用」

Status: before-first-deploy（2026-08-28 裁決：本機單人階段不修）。
關聯：`app/identity/routes.py` accept_invite；前端 `AcceptInvitePage`。

成因：accept_invite 不比對 invite.email 與登入者 email；且 `AcceptInvitePage` 一掛載就自動接受，沒有確認步驟。
影響：拿到連結的任何人都能加入組織。上雲前必還。
