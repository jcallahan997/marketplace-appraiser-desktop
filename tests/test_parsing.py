"""Tests for generic parsing utilities."""

import pytest

from marketplace_appraiser.utils.parsing import parse_listing_age, parse_price


class TestParsePrice:
    def test_simple_integer(self):
        assert parse_price("$5,000") == 5000.0

    def test_no_dollar_sign(self):
        # parse_price requires $ prefix — bare numbers return None
        assert parse_price("12000") is None

    def test_with_decimals(self):
        assert parse_price("$1,234.56") == 1234.56

    def test_price_in_text(self):
        assert parse_price("Listed at $3,500 firm") == 3500.0

    def test_free(self):
        # "Free" has no $ amount — returns None
        assert parse_price("Free") is None

    def test_none_input(self):
        assert parse_price(None) is None

    def test_empty_string(self):
        assert parse_price("") is None

    def test_no_digits(self):
        assert parse_price("Contact for price") is None

    def test_already_numeric(self):
        # parse_price expects str input; numeric input is not handled
        assert parse_price("$7,500") == 7500.0

    def test_dollar_no_comma(self):
        assert parse_price("$8500") == 8500.0


class TestParseListingAge:
    """parse_listing_age returns Optional[int] (days), not a tuple."""

    def test_weeks_ago(self):
        assert parse_listing_age("Listed 3 weeks ago") == 21

    def test_days_ago(self):
        assert parse_listing_age("5 days ago") == 5

    def test_hours_ago(self):
        assert parse_listing_age("Listed 6 hours ago") == 0

    def test_months_ago(self):
        assert parse_listing_age("2 months ago") == 60

    def test_one_week(self):
        assert parse_listing_age("a week ago") == 7

    def test_today(self):
        assert parse_listing_age("today") == 0

    def test_yesterday(self):
        assert parse_listing_age("yesterday") == 1

    def test_none_input(self):
        assert parse_listing_age(None) is None

    def test_empty_string(self):
        assert parse_listing_age("") is None

    def test_no_match(self):
        assert parse_listing_age("Some random text") is None
