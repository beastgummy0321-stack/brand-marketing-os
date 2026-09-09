"""app/schedule/creative.py — the coordinate vocabulary constant of the loop (ADR 0057, 0064):
the seven dimension names `CONSTITUTION.md` rule 5 signs, shared by `repository.py`
(`brand_coordinate`, `creative_candidate`), `performance.py` and `history.py`. Private to
app/schedule/ (container contract §1): only files inside this package import it.

票 05（ADR 0068 §5）：文案與視覺方向的產出搬去 `app.workbench` 之後，這個檔案原本用來把
代理回覆解析成每個節點一份內容的那一半程式碼（含它專屬的驗證函式，唯一呼叫端就是那半段，
退休後零呼叫端）一起退休；`COORDINATE_KEYS` 留下，是這個模組跟 `app.workbench`
（複製了一份，不 import，container contract 規則 5）共用的唯一事實。
"""

# `CONSTITUTION.md` 規則 5 簽下的七個維度名稱，逐字沿用，這支模組不定義任何別的名字。
COORDINATE_KEYS = ("audience", "pain", "angle", "hook", "proof", "offer", "format")
