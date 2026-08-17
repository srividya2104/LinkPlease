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

        # Re-run init_db
        db.init_db()
        assert len(db.get_all_rules()) == 1
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_startup_with_existing_custom_rule_does_not_create_default_rule():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        # Create database and insert custom rule
        db = Database(path)
        # Delete default rule to simulate pre-existing database with custom rule
        with db.get_connection() as conn:
            with conn:
                conn.execute("DELETE FROM rules")
                conn.execute("INSERT INTO rules (id, keyword, dm_message) VALUES ('rule_custom', 'DISCOUNT', '10% off')")

        # Instantiate Database again on existing file
        db2 = Database(path)
        rules = db2.get_all_rules()
        assert len(rules) == 1
        assert rules[0]["rule_id"] == "rule_custom"
        assert rules[0]["keyword"] == "DISCOUNT"
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_custom_rule_creation_and_matching(temp_db):
    engine = RuleEngine(temp_db)
    # temp_db already has default PRICE rule
    assert len(engine.get_rules()) == 1

    # Add custom rule
    custom = engine.create_rule(keyword="SHIPPING", dm_message="Shipping info")
    assert len(engine.get_rules()) == 2

    # Match PRICE
    matches_price = engine.match_rules("Can I get the price?")
    assert len(matches_price) == 1
    assert matches_price[0]["keyword"] == "PRICE"

    # Match SHIPPING
    matches_shipping = engine.match_rules("Is SHIPPING free?")
    assert len(matches_shipping) == 1
    assert matches_shipping[0]["keyword"] == "SHIPPING"
