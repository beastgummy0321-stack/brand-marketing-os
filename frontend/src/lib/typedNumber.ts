/** F50 Contract I (decision 11): a number field sends what was typed. The rule table is the server's
 * (`app/core/input_rules.py`): it parses the text, refuses with one sentence naming the field, and the screen prints
 * that sentence. The browser never turns a blank into 0 (`Number("")` is 0 — how a blank spend cap used to be saved
 * as 0) and keeps no bound of its own. This is the only file the `clientRules` scan lets call `Number(`.
 *
 * `typedValue(text)` = the trimmed text, or `null` when nothing was typed (blank = unknown, the server decides). */
export function typedValue(text: string): string | null {
  const trimmed = text.trim();
  return trimmed === "" ? null : trimmed;
}
