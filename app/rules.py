from typing import Any, Dict, List
import unicodedata
import uuid
from app.database import Database


class RuleEngine:

    def __init__(self, db: Database):
        self.db = db

    def create_rule(self, keyword: str, dm_message: str) -> Dict[str, Any]:
        rule_id = f"rule_{uuid.uuid4().hex[:12]}"
        return self.db.insert_rule(
            rule_id=rule_id, keyword=keyword, dm_message=dm_message
        )

    def get_rules(self) -> List[Dict[str, Any]]:
        return self.db.get_all_rules()

    @staticmethod
    def _clean_str(s: str) -> str:
        if not s:
            return ""
        nfkd = unicodedata.normalize("NFKD", s.lower())
        ascii_text = "".join(c for c in nfkd if not unicodedata.combining(c))
        return "".join(c for c in ascii_text if c.isalnum())

    def match_rules(self, text: str) -> List[Dict[str, Any]]:
        if not text:
            return []

        text_lower = text.lower()
        text_clean = self._clean_str(text)
        all_rules = self.get_rules()
        matched = []

        for rule in all_rules:
            kw_lower = rule["keyword"].lower()
            kw_clean = self._clean_str(rule["keyword"])

            # 1. Strict case-insensitive substring match
            if kw_lower and kw_lower in text_lower:
                matched.append(rule)
                continue

            # 2. Normalized alphanumeric match (removes accents, spaces, dots, hyphens, underscores)
            if kw_clean and kw_clean in text_clean:
                matched.append(rule)
                continue

        return matched
