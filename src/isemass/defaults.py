"""Built-in settings defaults."""

from __future__ import annotations

from typing import Any

DEFAULT_SETTINGS: dict[str, dict[str, Any]] = {
    "coa": {
        "verbose": False,
        "max_workers": 20,
        "insecure": False,
    },
    "swauth": {
        "verbose": False,
    },
}
