"""app/workbench/image_port.py — reserved seat for in-site image generation
(ARCHITECTURE.md §5.11). Not a feature: no provider, no API key, no HTTP client, no cost.

Connecting a real adapter is a separate feature with its own approval, because it spends
money. A real adapter would have to hand back, per image: a provider name, a job id, and a
storage key — the columns `workbench_output` already reserves for this. Nothing here does
that yet.

No registry, no config value, no environment variable, no abstract base class with one
implementation — there is exactly one implementation, and it does nothing.
"""


def connected() -> bool:
    """Always `False` until a real adapter exists."""
    return False


def generate(*args, **kwargs):
    """No provider is wired up. Callers must not reach this — it exists so the shape of a
    future call site is visible, not so it can be invoked."""
    raise NotImplementedError("image_port_not_connected")
