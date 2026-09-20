"""app/tests/test_ads_external_models.py — F18-I02: `Availability` was widened to include
`"derived_zero"` (F18-I01 review ceiling, `app/ads/tracked_zero.py`) -- this is the one place that
proves the model itself accepts it instead of only the raw SQL write path `tracked_zero.apply`
uses.
"""

import unittest

from pydantic import ValidationError

from app.ads.external_models import ExternalObservation


class AvailabilityDerivedZeroTest(unittest.TestCase):
    def test_result_count_availability_accepts_derived_zero(self):
        observation = ExternalObservation(
            entity_id="e", day="2026-01-01", metric_scope="ad", attribution_key="x", source="x",
            availability={"result_count": "derived_zero"},
        )
        self.assertEqual(observation.availability["result_count"], "derived_zero")

    def test_unknown_availability_value_still_rejected(self):
        with self.assertRaises(ValidationError):
            ExternalObservation(
                entity_id="e", day="2026-01-01", metric_scope="ad", attribution_key="x",
                source="x", availability={"result_count": "definitely_not_a_real_state"},
            )


if __name__ == "__main__":
    unittest.main()
