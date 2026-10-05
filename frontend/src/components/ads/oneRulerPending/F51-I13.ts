/** oneRuler.test.ts pending entries that F51-I13 removes (moved out of `NOT_A_RULER` by F51-I04): the review round
 * reads the served period `ad_spend` and `ad_result_view`. Empty this file (or delete it) when done. */
export const notARuler = [
  { file: "components/ads/review/reviewFlow.ts", text: "mirrors `app/ads/triage.py::_ad_spend` exactly", why: "debt: feature C/D (W11/W16) — an ad's window spend is summed in the browser" },
  { file: "components/ads/review/reviewFlow.ts", text: "mirrors `app/ads/triage.py::_ad_window`", why: "debt: feature C/D (W11/W16) — the ad's result view is picked in the browser by triage's rule" },
];
