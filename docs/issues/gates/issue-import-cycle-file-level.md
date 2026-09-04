# `ImportCycleScanTest` 看不到套件內部的環：降到檔案層

Status: approved——使用者 2026-09-04 已批准「裝」，尚未執行；下一步 /slice ① 改名成 `01-import-cycle-file-level.md` 填四欄。
關聯：`test_architecture_boundaries.py:391-416`（`_layer_import_graph()`）；`docs/tech-debt.md` §二。

把掃描從套件層降到檔案層。2026-09-04 已量：降到檔案層重掃整個 `app/`，**今天違規數是 0**
（T5 拆 `routes.py` 時連帶解掉了），所以裝它是「以後再犯也擋得住」的保險。**先弄紅一次才算數。**
