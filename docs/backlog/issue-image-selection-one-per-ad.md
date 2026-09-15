# Image sets allow many selections, and the creative that actually ran is not recorded

Status: not planned. Found reviewing F07 (2026-09-15).

- Selecting versions is multi-select with no limit or warning (`SetStudioPage.tsx:326-332`);
  `select_version_for_set` stamps `adopted_at` on one row only (`app/workbench/repository.py:303-305`)
  and nothing constrains `adopted_at`. Multi-select came from F02-I02 for copy (ARCHITECTURE.md §5.4).
- For an ads-dispatched 單圖／輪播 set only the earliest-selected row counts: `adopted_output`
  (repository.py:401-405) feeds the manual publish checklist (`app/ads/routes.py:575-597`) and
  closeout visual learning (`app/ads/visual_learning.py:67-73`). Deselecting and reselecting a row
  moves it to last.
- Extra selections still:
  - render one ② 變體 card per selected 單圖 version (repository.py:1226, `image_cards.py:58`);
  - raise `look_history`'s adopted counts (repository.py:554), which order exploration, so looks
    that never ran count as tried;
  - let the 查看 Prompt panel show a different version than the checklist (`ImagePart.tsx:37-38`).
- `ads_ad` has no column for the output row that went live; closeout infers it from the earliest
  selection, so changing the selection after launch re-attributes the learning.
- Revisit: one selection per image set for ads-dispatched sets (copy keeps multi-select), and record
  the live creative on the ad at publish.
