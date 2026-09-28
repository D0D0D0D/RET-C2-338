"""AgentCore Platform v1.0 — RET-C2-338 domain service.

Loads the product catalogue and promotion rules. No business logic, routing, or
credentials here. `personalisation_engine` calls this; cross-sell is derived from
catalogue + promotion rules ONLY — there is no pricing-engine dependency.
"""

from __future__ import annotations

import json
import os
from typing import Any


class CatalogueService:
    """Reads the product catalogue and promotion rules from JSON files.

    Inputs can also be injected directly (catalogue / promotion_rules) for
    tests, bypassing file IO. File contents are session-independent reference
    data (no customer PII).
    """

    def __init__(
        self,
        catalogue: list[dict[str, Any]] | None = None,
        promotion_rules: list[dict[str, Any]] | None = None,
        catalogue_path: str | None = None,
        promotion_rules_path: str | None = None,
    ) -> None:
        self._catalogue = catalogue
        self._promotion_rules = promotion_rules
        self._catalogue_path = catalogue_path
        self._promotion_rules_path = promotion_rules_path

    def load_catalogue(self) -> list[dict[str, Any]]:
        """Return the product catalogue (list of SKU dicts)."""
        if self._catalogue is not None:
            return self._catalogue
        return self._read_json(self._catalogue_path)

    def load_promotion_rules(self) -> list[dict[str, Any]]:
        """Return the promotion rules (list of rule dicts)."""
        if self._promotion_rules is not None:
            return self._promotion_rules
        return self._read_json(self._promotion_rules_path)

    @staticmethod
    def _read_json(path: str | None) -> list[dict[str, Any]]:
        if not path or not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
