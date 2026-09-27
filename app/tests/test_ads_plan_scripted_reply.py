"""Shape tripwire: `providers.SCRIPTED_REPLIES["ads_delivery_plan"]` (the e2e backend's reply,
used by `frontend/e2e/ads-cold-start.spec.ts`) must pass `plan._validate_reply` for the roles the
scripted `ads_strategy` reply allocates, or the e2e adopt step 400s instead of expanding
the plan.

F33-I00: the scripted provider is prompt-aware (Contract P in `.work/features/F33.md`): the
strategy reply allocates only the roles the prompt lists under `【可用角色】`, and the delivery-plan
reply builds one group per adopted-allocation line `- <role>（<label>）：<pct>%`."""

import json
import unittest

from app.ads import plan
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


if __name__ == "__main__":
    unittest.main()
