"""app/tests/test_ads_stages.py — D線票1（GitHub issue #43）檔期五格階段推導。

app/ads/stages.derive_stage 是純函數（不碰資料庫），驗收重點是：單看 campaign_cycle.status
分不出素材／交接包／投放前檢查這三格（同屬 PRODUCTION 這個狀態窗口），必須併用
素材是否已採用、交接包是否已建置／已啟用這些既有訊號才分得出來——這裡逐一測這三格的分界。
"""

import unittest

from app.ads import stages


class DeriveStagePlanAndLiveTest(unittest.TestCase):
    def test_pre_production_statuses_are_stage_1(self):
        for status in ("PLANNING", "PLAN_SELECT", "REVIEW"):
            self.assertEqual(stages.derive_stage(status), 1, status)

    def test_post_production_statuses_are_stage_5(self):
        for status in ("LIVE", "EVALUATING", "CLOSED"):
            self.assertEqual(stages.derive_stage(status), 5, status)

    def test_unknown_status_falls_back_to_stage_1(self):
        self.assertEqual(stages.derive_stage("SOMETHING_NEW"), 1)

    def test_activated_package_forces_stage_5_even_if_status_lags(self):
        # 防線：就算狀態還沒同步成 LIVE，只要有交接包啟用了就是成效格
        self.assertEqual(
            stages.derive_stage("PRODUCTION", has_adopted=True, package_count=1,
                                 activated_count=1),
            5,
        )


class DeriveStageProductionWindowBoundariesTest(unittest.TestCase):
    """PRODUCTION 狀態窗口內的三格分界：素材／交接包／投放前檢查。"""

    def test_creative_not_adopted_is_stage_2(self):
        self.assertEqual(
            stages.derive_stage("PRODUCTION", has_adopted=False, package_count=0), 2)
        # 就算誤傳了 package_count（理論上不會發生：沒採用素材建不出交接包），
        # has_adopted 沒過一律先算素材格
        self.assertEqual(
            stages.derive_stage("PRODUCTION", has_adopted=False, package_count=3), 2)

    def test_adopted_but_no_package_built_is_stage_3(self):
        self.assertEqual(
            stages.derive_stage("PRODUCTION", has_adopted=True, package_count=0), 3)

    def test_package_built_is_stage_4(self):
        self.assertEqual(
            stages.derive_stage("PRODUCTION", has_adopted=True, package_count=1), 4)

    def test_boundary_exactly_at_has_adopted_flip(self):
        # 同樣 package_count=0，唯一差異是 has_adopted，分界必須確實落在這裡
        self.assertEqual(
            stages.derive_stage("PRODUCTION", has_adopted=False, package_count=0), 2)
        self.assertEqual(
            stages.derive_stage("PRODUCTION", has_adopted=True, package_count=0), 3)

    def test_boundary_exactly_at_package_count_flip(self):
        self.assertEqual(
            stages.derive_stage("PRODUCTION", has_adopted=True, package_count=0), 3)
        self.assertEqual(
            stages.derive_stage("PRODUCTION", has_adopted=True, package_count=1), 4)

    def test_checklist_completeness_is_not_a_gate(self):
        # 投放前檢查清單完不完成不影響階段判讀（checklist.py 既有原則：兩類都不擋流程）。
        # derive_stage 不接受清單完成度做為關卡參數；這裡確認不管清單狀態如何，
        # 只要交接包建了、還沒啟用，就是同一個投放前檢查格。
        self.assertEqual(
            stages.derive_stage("PRODUCTION", has_adopted=True, package_count=2,
                                 activated_count=0),
            4,
        )


class StageLabelsTest(unittest.TestCase):
    def test_five_labels_in_order(self):
        self.assertEqual(stages.STAGE_LABELS,
                          ["計畫", "素材", "交接包", "投放前檢查", "成效"])


if __name__ == "__main__":
    unittest.main()
