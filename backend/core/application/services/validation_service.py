from __future__ import annotations

from typing import Any, Dict

from knowledgebase import strategies as kstrategies


class ValidationService:
    def __init__(self):
        pass

    def validate(self, strategy) -> Dict[str, Any]:
        return kstrategies.validate_strategy(strategy)
