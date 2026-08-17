import tempfile
import os
import pytest
from app.database import Database
from app.rules import RuleEngine


def test_empty_database_startup_creates_default_price_rule():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = Database(path)
        rules = db.get_all_rules()
        assert len(rules) == 1
        assert rules[0]["rule_id"] == "rule_default_price"
        assert rules[0]["keyword"] == "PRICE"
        assert rules[0]["dm_message"] == "Here is the price list. Thank you!"
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_rerunning_db_init_does_not_duplicate_default_rule():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = Database(path)
        assert len(db.get_all_rules()) == 1

        db.init_db()
        assert len(db.get_all_rules()) == 1
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_startup_with_existing_custom_rule_does_not_create_default_rule():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = Database(path)
        with db.get_connection() as conn:
            with conn:
                conn.execute("DELETE FROM rules")
                conn.execute("INSERT INTO rules (id, keyword, dm_message) VALUES ('rule_custom', 'DISCOUNT', '10% off')")

        db2 = Database(path)
        rules = db2.get_all_rules()
        assert len(rules) == 1
        assert rules[0]["rule_id"] == "rule_custom"
        assert rules[0]["keyword"] == "DISCOUNT"
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_unicode_and_robust_keyword_matching(temp_db):
    engine = RuleEngine(temp_db)
    # Default PRICE rule is seeded in temp_db

    # Test cases required by specification
    test_cases = [
        ("PRICE", True),
        ("price", True),
        ("P.R.I.C.E", True),
        ("p r i c e", True),
        ("p-r-i-c-e", True),
        ("p_r_i_c_e", True),
        ("PRÍCE", True),
        ("PRÌCE", True),
        ("PRÎCE", True),
        ("unrelated text", False),
    ]

    for text, expected_match in test_cases:
        matches = engine.match_rules(text)
        if expected_match:
            assert len(matches) == 1, f"Expected '{text}' to match PRICE rule"
            assert matches[0]["keyword"] == "PRICE"
        else:
            assert len(matches) == 0, f"Expected '{text}' NOT to match any rule"
