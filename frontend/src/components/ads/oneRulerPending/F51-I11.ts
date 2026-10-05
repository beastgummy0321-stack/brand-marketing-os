/** oneRuler.test.ts pending entries that F51-I11 removes (moved out of `NOT_A_RULER` by F51-I04): the performance tab
 * prints the served `learning_sentence`. Empty this file (or delete it) when done. */
export const notARuler = [
  { file: "components/ads/PerformanceTab.tsx", text: "跟 `app/ads/learning.py::_sentence` 同一套公式", why: "debt: feature C/D (W11/W16) — the closeout learning sentence is rebuilt in the browser" },
];
