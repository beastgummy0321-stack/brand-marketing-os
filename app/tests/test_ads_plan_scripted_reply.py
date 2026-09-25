"""Shape tripwire: `providers.SCRIPTED_REPLIES["ads_delivery_plan"]` (the e2e backend's reply,
used by `frontend/e2e/ads-cold-start.spec.ts`) must pass `plan._validate_reply` for the roles the
scripted `ads_strategy` reply allocates, or the e2e adopt step 400s instead of expanding
the plan."""

import unittest

from app.ads import plan
from app.llm import providers


class ScriptedDeliveryPlanValidatesTest(unittest.TestCase):
    def test_scripted_plan_matches_scripted_strategy_roles(self):
        roles = {row["role"] for row in providers.SCRIPTED_REPLIES["ads_strategy"]["allocation"]}
        groups = plan._validate_reply(providers.SCRIPTED_REPLIES["ads_delivery_plan"], roles)
        self.assertIsNotNone(groups)
        self.assertEqual({group["role"] for group in groups}, roles)


if __name__ == "__main__":
    unittest.main()
