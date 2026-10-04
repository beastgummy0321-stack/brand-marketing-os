"""Shape tripwire: `providers.SCRIPTED_REPLIES["ads_delivery_plan"]` (the e2e backend's reply,
used by `frontend/e2e/ads-cold-start.spec.ts`) must pass `plan._validate_reply` for the roles the
scripted `ads_strategy` reply allocates, or the e2e adopt step 400s instead of expanding
the plan.

F33-I00: the scripted provider is prompt-aware (Contract P in `.work/features/F33.md`): the
strategy reply allocates only the roles the prompt lists under `【可用角色】`, and the delivery-plan
reply builds one group per adopted-allocation line `- <role>（<label>）：<pct>%`."""

import json
import unittest

from app.ads import plan, planner_context
from app.llm import providers

_ROLE_LABELS = {"new": "新客", "retarget": "再行銷", "explore": "探索"}


def _scripted(task_type: str, prompt: str) -> dict:
    provider = providers.ScriptedProvider(providers.SCRIPTED_REPLIES[task_type])
    response = provider.complete(
        model="m", system=None, messages=[{"role": "user", "content": prompt}], max_tokens=10,
    )
    return json.loads(response.output_text)


def _adopted_lines(allocation: list) -> str:
    # Same line format as `plan.adopt_strategy` builds for the delivery-plan prompt.
    return "\n".join(
        f"- {row['role']}（{_ROLE_LABELS[row['role']]}）：{row['pct']:g}%，{row['rationale']}"
        for row in allocation
    )


class ScriptedDeliveryPlanValidatesTest(unittest.TestCase):
    def test_scripted_plan_matches_scripted_strategy_roles(self):
        roles = {row["role"] for row in providers.SCRIPTED_REPLIES["ads_strategy"]["allocation"]}
        groups = plan._validate_reply(providers.SCRIPTED_REPLIES["ads_delivery_plan"], roles)
        self.assertIsNotNone(groups)
        self.assertEqual({group["role"] for group in groups}, roles)

    def test_two_offered_roles_flow_from_strategy_into_a_valid_plan(self):
        strategy = _scripted("ads_strategy", "策略提示\n\n【可用角色】\nnew、explore\n\n其他段落")
        self.assertEqual([row["role"] for row in strategy["allocation"]], ["new", "explore"])
        self.assertEqual([row["pct"] for row in strategy["allocation"]], [60, 40])
        roles = {row["role"] for row in strategy["allocation"]}

        plan_prompt = (
            "部門提示\n\n## 這次投放已採用的角色分配\n\n" + _adopted_lines(strategy["allocation"])
        )
        reply = _scripted("ads_delivery_plan", plan_prompt)
        groups = plan._validate_reply(reply, roles)
        self.assertIsNotNone(groups)
        self.assertEqual([group["role"] for group in groups], ["new", "explore"])
        self.assertTrue(all(len(group["ads"]) == 1 for group in groups))

    def test_plan_prompt_without_adopted_lines_keeps_three_groups(self):
        reply = _scripted("ads_delivery_plan", "部門提示，沒有採用清單")
        self.assertEqual(reply, providers.SCRIPTED_REPLIES["ads_delivery_plan"])

    def test_first_ad_takes_the_first_listed_offer_key(self):
        """F44-I02: with 【這期可用的優惠】 in the prompt an all-`none` plan is refused, so the
        scripted reply's first group uses the first listed key; a vocabulary row
        (`- offer｜…`) or the department file naming the header is not a listed offer."""
        allocation = providers.SCRIPTED_REPLIES["ads_strategy"]["allocation"]
        base = (
            "部門提示：【這期可用的優惠】有列時至少一支廣告要用\n\n## 這次投放已採用的角色分配\n\n"
            + _adopted_lines(allocation)
        )
        vocabulary = "\n\n【座標詞彙】\n- offer｜bundle｜組合優惠\n- offer｜none｜無優惠"
        offers = (
            "\n\n" + planner_context.OFFERS_HEADER
            + "\n- offer=free_shipping｜滿 NT$999 免運"
            + "\n- offer=bundle｜三盒組優惠價 NT$999（原價 NT$1,197）"
        )

        reply = _scripted("ads_delivery_plan", base + offers + vocabulary)
        used = [group["ads"][0]["coordinates"]["offer"] for group in reply["groups"]]
        self.assertEqual(used, ["free_shipping", "e2e", "e2e"])
        roles = {row["role"] for row in allocation}
        self.assertIsNotNone(plan._validate_reply(reply, roles))
        # The shared template is not mutated by the per-prompt reply.
        template_ad = providers.SCRIPTED_REPLIES["ads_delivery_plan"]["groups"][0]["ads"][0]
        self.assertEqual(template_ad["coordinates"]["offer"], "e2e")

        without = _scripted("ads_delivery_plan", base + vocabulary)
        self.assertEqual(
            [group["ads"][0]["coordinates"]["offer"] for group in without["groups"]],
            ["e2e", "e2e", "e2e"],
        )

    def test_listed_customer_groups_bind_every_ad_to_the_first_group(self):
        """F46-I01 (Contract A): with 【這個賣法的顧客】 groups listed every ad takes
        `customer_group: 1` and 第 1 群's first pain key, so the plan's binding check passes;
        the 「還沒有建顧客群」 one-liner or no section leaves the reply without the key."""
        allocation = providers.SCRIPTED_REPLIES["ads_strategy"]["allocation"]
        base = "部門提示：【這個賣法的顧客】有列時每支廣告要填 customer_group\n\n" \
            "## 這次投放已採用的角色分配\n\n" + _adopted_lines(allocation)
        customers = (
            "\n\n【這個賣法的顧客】"
            "\n第 1 群：下班後夜跑的上班族｜煩惱：怕買錯（pain=uncertainty）、怕麻煩（pain=effort）"
            "｜顧客會說：（沒寫）｜什麼時候用：（沒寫）"
            "\n第 2 群：帶小孩散步的爸媽｜煩惱：怕麻煩（pain=effort）｜顧客會說：（沒寫）"
            "｜什麼時候用：（沒寫）"
        )

        reply = _scripted("ads_delivery_plan", base + customers)
        ads = [ad for group in reply["groups"] for ad in group["ads"]]
        self.assertEqual({ad["customer_group"] for ad in ads}, {1})
        self.assertEqual({ad["coordinates"]["pain"] for ad in ads}, {"uncertainty"})
        roles = {row["role"] for row in allocation}
        groups = plan._validate_reply(reply, roles)
        assert groups is not None
        listed = [
            {"id": "pcg_1", "who": "下班後夜跑的上班族", "pain_keys": ["uncertainty", "effort"]},
            {"id": "pcg_2", "who": "帶小孩散步的爸媽", "pain_keys": ["effort"]},
        ]
        self.assertTrue(plan._bind_customer_groups(groups, listed, {"uncertainty", "effort"}))
        template_ad = providers.SCRIPTED_REPLIES["ads_delivery_plan"]["groups"][0]["ads"][0]
        self.assertNotIn("customer_group", template_ad)
        self.assertEqual(template_ad["coordinates"]["pain"], "e2e")

        for tail in ("\n\n【這個賣法的顧客】（這個商品還沒有建顧客群）", ""):
            without = _scripted("ads_delivery_plan", base + tail)
            for group in without["groups"]:
                for ad in group["ads"]:
                    self.assertNotIn("customer_group", ad)
                    self.assertEqual(ad["coordinates"]["pain"], "e2e")

    def test_a_kept_ranking_row_of_a_listed_group_is_reused_by_the_first_ad(self):
        """F46-I04 (Contract G): the plan is refused unless one ad reuses a 留下 (group, angle),
        so the first group's ads take the kept row's group number (with that group's first pain)
        and the first ad its angle key; 換掉 rows and 「這期沒列」 rows are not reused."""
        allocation = providers.SCRIPTED_REPLIES["ads_strategy"]["allocation"]
        base = "部門提示：【上幾期的排名】有列時要沿用一個留下\n\n" \
            "## 這次投放已採用的角色分配\n\n" + _adopted_lines(allocation)
        ranking = (
            "\n\n【上幾期的排名（程式排的；每筆＝花費÷成交）】"
            "\n- 三盒組第 1／3 名｜留下・相對最好，仍高於上限｜顧客群 這期沒列：舊的一群｜「甲」"
            "｜每筆 555｜賣 5 筆｜花 2,775｜a（angle=old_angle）"
            "\n- 三盒組第 2／3 名｜換掉｜顧客群 1｜「乙」｜每筆 1,643｜賣 2 筆｜花 3,286"
            "｜b（angle=cut_angle）"
            "\n- 三盒組第 3／3 名｜留下・樣本少｜顧客群 2｜「丙」｜每筆 290｜賣 4 筆｜花 1,160"
            "｜未設定（audience=none）、陪你撐完（angle=late_night）"
        )
        customers = (
            "\n\n【這個賣法的顧客】"
            "\n第 1 群：通勤上班族｜煩惱：怕麻煩（pain=effort）｜顧客會說：（沒寫）"
            "｜什麼時候用：（沒寫）"
            "\n第 2 群：學生備考｜煩惱：熬夜（pain=late）、怕貴（pain=cost）｜顧客會說：（沒寫）"
            "｜什麼時候用：（沒寫）"
        )

        reply = _scripted("ads_delivery_plan", base + ranking + customers)

        first = reply["groups"][0]["ads"][0]
        self.assertEqual(first["customer_group"], 2)
        self.assertEqual(first["coordinates"]["angle"], "late_night")
        self.assertEqual(first["coordinates"]["pain"], "late")
        self.assertEqual(
            [group["ads"][0]["customer_group"] for group in reply["groups"][1:]], [1, 1],
        )
        roles = {row["role"] for row in allocation}
        self.assertIsNotNone(plan._validate_reply(reply, roles))

        without = _scripted("ads_delivery_plan", base + customers)
        self.assertEqual(without["groups"][0]["ads"][0]["customer_group"], 1)
        self.assertEqual(without["groups"][0]["ads"][0]["coordinates"]["angle"], "e2e")

    def test_carried_ads_leave_k_ads_roles_without_a_carried_ad_first(self):
        """F48 Contract K: with 【已沿用的廣告】 and 「請再規劃 K 則」 the scripted plan writes
        `min(K, roles)` ads, one per role, roles no carried ad covers first; a covered role's ads
        bind the carried ads' 第 N 群. The reply passes `_validate_reply` with the same limits
        `adopt_strategy` passes."""
        allocation = providers.SCRIPTED_REPLIES["ads_strategy"]["allocation"]
        base = "部門提示\n\n## 這次投放已採用的角色分配\n\n" + _adopted_lines(allocation)
        customers = (
            "\n\n【這個賣法的顧客】"
            "\n第 1 群：通勤上班族｜煩惱：怕麻煩（pain=effort）｜顧客會說：（沒寫）"
            "\n第 2 群：學生備考｜煩惱：熬夜（pain=late）｜顧客會說：（沒寫）"
        )
        carried_lines = (
            "\n\n【已沿用的廣告】（程式已經放進投放組）"
            "\n- 「上一期留下的」｜投放組 new｜顧客群 2｜audience=a、pain=late、angle=b"
        )
        roles = {row["role"] for row in allocation}
        carried = [{"target": "new", "ad": {"name": "上一期留下的"}}]
        room = {"new": 2, "retarget": 3, "explore": 3}

        two = _scripted("ads_delivery_plan",
                        base + customers + carried_lines + "\n請再規劃 2 則")
        self.assertEqual([g["role"] for g in two["groups"]], ["retarget", "explore"])
        self.assertIsNotNone(plan._validate_reply(
            two, roles, covered={"new"}, room=room, limit=2, taken={"上一期留下的"}))

        three = _scripted("ads_delivery_plan",
                          base + customers + carried_lines + "\n請再規劃 5 則")
        self.assertEqual([g["role"] for g in three["groups"]], ["retarget", "explore", "new"])
        new_group = three["groups"][2]
        self.assertEqual(new_group["ads"][0]["customer_group"], 2)
        self.assertEqual(new_group["ads"][0]["coordinates"]["pain"], "late")
        validated = plan._validate_reply(
            three, roles, covered={"new"}, room=room, limit=5, taken={"上一期留下的"})
        assert validated is not None
        listed = [{"id": "pcg_1", "who": "通勤上班族", "pain_keys": ["effort"]},
                  {"id": "pcg_2", "who": "學生備考", "pain_keys": ["late"]}]
        self.assertTrue(plan._bind_customer_groups(validated, listed, set()))
        carried[0]["ad"]["customer_group_id"] = "pcg_2"
        self.assertTrue(plan._same_people_as_carried(validated, carried))

        # Without the K line (nothing carried) the reply is the unchanged one-per-role plan.
        plain = _scripted(
            "ads_delivery_plan", base + "\n\n【已沿用的廣告】（上一期沒有留下的廣告可以沿用）",
        )
        self.assertEqual([g["role"] for g in plain["groups"]], ["new", "retarget", "explore"])


if __name__ == "__main__":
    unittest.main()
