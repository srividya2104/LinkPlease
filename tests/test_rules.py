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


def test_robust_keyword_matching(temp_db):
    engine = RuleEngine(temp_db)
    # Default PRICE rule is seeded in temp_db

    # 1. Normal case-insensitive substring
    m1 = engine.match_rules("PRICE")
    assert len(m1) == 1

    m2 = engine.match_rules("price please")
    assert len(m2) == 1

    # 2. Punctuation-separated keyword
    m3 = engine.match_rules("P.R.I.C.E")
    assert len(m3) == 1

    # 3. Whitespace-separated keyword
    m4 = engine.match_rules("p r i c e")
    assert len(m4) == 1

    # 4. Hyphen-separated keyword
    m5 = engine.match_rules("p-r-i-c-e")
    assert len(m5) == 1

    # 5. Underscore-separated keyword
    m6 = engine.match_rules("p_r_i_c_e")
    assert len(m6) == 1

    # 6. Keyword inside larger word
    m7 = engine.match_rules("What a pricey item")
    assert len(m7) == 1

    # 7. Unrelated text not matching
    m8 = engine.match_rules("Hello world")
    assert len(m8) == 0
