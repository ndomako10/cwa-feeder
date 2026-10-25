"""How the feeder reads a series from Chaptarr's ebook record.

Chaptarr's API gives the series only as one string, "Name #N", on the
ebook's own record (2026-10-19).
"""

from feeder import parse_series


class TestParseSeries:
    def test_given_a_series_and_number_returns_both(self):
        assert parse_series("The Hunger Games #3") == ("The Hunger Games", "3")

    def test_given_a_fractional_number_keeps_it_as_written(self):
        assert parse_series("The Stormlight Archive #2.5") == (
            "The Stormlight Archive",
            "2.5",
        )

    def test_given_a_hash_inside_the_series_name_splits_at_the_last_one(self):
        assert parse_series("Club #9 Mysteries #4") == ("Club #9 Mysteries", "4")

    def test_given_no_series_returns_none(self):
        assert parse_series(None) is None

    def test_given_an_empty_series_returns_none(self):
        assert parse_series("") is None

    def test_given_a_series_with_no_number_returns_the_name_without_a_number(self):
        assert parse_series("Discworld") == ("Discworld", None)

    def test_given_a_hash_in_the_name_and_no_number_keeps_the_whole_name(self):
        assert parse_series("Club #9 Mysteries") == ("Club #9 Mysteries", None)
