"""Built-in defaults and generated settings template."""

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

SETTINGS_TEMPLATE = """[coa]
# Enable extra output for CoA operations.
verbose = false

# API username. Passwords/tokens are intentionally not stored here.
username = "bob-example"

# host = "ise-mnt.example.com"
# node = "ise-psn01"
max_workers = 20
insecure = false

[swauth]
# Enable extra output for switch reauthentication operations.
verbose = false
"""

