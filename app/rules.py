from typing import Any, Dict, List
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

    def match_rules(self, text: str) -> List[Dict[str, Any]]:
        if not text:
            return []

        text_lower = text.lower()
        all_rules = self.get_rules()
        matched = []
        for rule in all_rules:
            if rule["keyword"].lower() in text_lower:
                matched.append(rule)
        return matched
