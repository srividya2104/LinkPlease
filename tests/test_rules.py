import pytest
from app.rules import RuleEngine


def test_rule_matching_case_insensitive_and_substring(temp_db):
    engine = RuleEngine(temp_db)
    engine.create_rule(keyword="PRICE", dm_message="Price is $50")
    engine.create_rule(keyword="shipping", dm_message="Shipping is free")

    # Case insensitive + substring match
    matches1 = engine.match_rules("Can I get the price please?")
    assert len(matches1) == 1
    assert matches1[0]["keyword"] == "PRICE"

    matches2 = engine.match_rules("Is SHIPPING available?")
    assert len(matches2) == 1
    assert matches2[0]["keyword"] == "shipping"

    # Multiple matching rules
    matches3 = engine.match_rules(
        "What is the PRICE and does it include SHIPPING?"
    )
    assert len(matches3) == 2

    # No match
    matches4 = engine.match_rules("Hello world")
    assert len(matches4) == 0
