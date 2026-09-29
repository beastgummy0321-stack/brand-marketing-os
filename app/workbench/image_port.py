"""app/workbench/image_port.py — reserved seat for in-site image generation
(ARCHITECTURE.md §5.11). Not a feature: no provider, no API key, no HTTP client, no cost.

F38 decision 6 fixes the call shape a future adapter must honour; the body still does nothing.

- Input: the prompt cards the 圖片 tab already shows (`image_cards` shape, `{"label", "text"}`),
  plus the aspect ratio (e.g. "4:5"), how many images, and the brand.
- Output, per image: a `GeneratedImage` — `provider`, `job_id` and `storage_key` are exactly the
  three columns `workbench_output` already reserves for this; `prompt_label` names the card the
  image was generated from.

Which provider to connect and the cost cap per run are a user decision taken in a separate,
approved feature, because it spends money. Nothing in this module may spend money or call the
network. The prompt cards remain the product until then.

No registry, no config value, no environment variable, no abstract base class with one
implementation — there is exactly one implementation, and it does nothing.
"""

from typing import TypedDict


class GeneratedImage(TypedDict):
    provider: str
    job_id: str
    storage_key: str
    prompt_label: str


def connected() -> bool:
    """Always `False` until a real adapter exists."""
    return False


def generate(prompt_cards: list[dict], *, aspect: str, count: int,
             brand_id: str) -> list[GeneratedImage]:
    """No provider is wired up. Callers must not reach this — it exists so the shape of a
    future call site is visible, not so it can be invoked."""
    raise NotImplementedError("image_port_not_connected")
