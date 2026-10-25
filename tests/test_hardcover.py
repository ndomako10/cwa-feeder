"""How the feeder reads a book from Hardcover's API.

The response below is the shape Hardcover gave for Catching Fire
(book 175780) on 2026-10-20, trimmed.
"""

import json
from unittest import mock

import pytest

from feeder import (
    HARDCOVER_URL,
    HardcoverError,
    fetch_hardcover_book,
    parse_hardcover_book,
)


def genre(name, count):
    return {"tag": name, "count": count, "category": "Genre"}


def hardcover_response(**overrides):
    book = {
        "title": "Catching Fire",
        "description": "The second novel in the series.",
        "release_date": "2009-09-01",
        "cached_tags": {
            "Genre": [genre("Dystopian", 17), genre("Young Adult", 15)],
            "Mood": [{"tag": "adventurous", "count": 9}],
        },
        "book_series": [{"position": 2, "series": {"name": "The Hunger Games"}}],
        "default_ebook_edition": {
            "isbn_13": "9780545227247",
            "publisher": {"name": "Scholastic Inc."},
        },
        "default_physical_edition": {
            "isbn_13": "9780439023498",
            "publisher": {"name": "Scholastic Press"},
        },
    }
    book.update(overrides)
    return {"data": {"books": [book]}}


class TestParseHardcoverBook:
    def test_given_a_full_record_returns_every_field(self):
        assert parse_hardcover_book(hardcover_response()) == {
            "description": "The second novel in the series.",
            "release_date": "2009-09-01",
            "genres": ["Dystopian", "Young Adult"],
            "series": ("The Hunger Games", "2"),
            "isbn": "9780545227247",
            "publisher": "Scholastic Inc.",
        }

    def test_given_a_fractional_position_keeps_it(self):
        response = hardcover_response(
            book_series=[{"position": 2.5, "series": {"name": "Stormlight"}}]
        )

        assert parse_hardcover_book(response)["series"] == ("Stormlight", "2.5")

    def test_given_a_series_with_no_position_returns_the_name_alone(self):
        response = hardcover_response(
            book_series=[{"position": None, "series": {"name": "Discworld"}}]
        )

        assert parse_hardcover_book(response)["series"] == ("Discworld", None)

    def test_given_no_series_returns_none_for_it(self):
        response = hardcover_response(book_series=[])

        assert parse_hardcover_book(response)["series"] is None

    def test_given_no_ebook_edition_takes_isbn_and_publisher_from_the_print_one(
        self,
    ):
        response = hardcover_response(default_ebook_edition=None)

        parsed = parse_hardcover_book(response)

        assert (parsed["isbn"], parsed["publisher"]) == (
            "9780439023498",
            "Scholastic Press",
        )

    def test_given_no_tags_returns_no_genres(self):
        response = hardcover_response(cached_tags=None)

        assert parse_hardcover_book(response)["genres"] == []

    def test_given_no_matching_book_returns_none(self):
        assert parse_hardcover_book({"data": {"books": []}}) is None

    def test_given_an_error_response_raises_rather_than_reading_it_as_no_book(
        self,
    ):
        with pytest.raises(HardcoverError, match="field 'nope' not found"):
            parse_hardcover_book({"errors": [{"message": "field 'nope' not found"}]})


class TestFetchHardcoverBook:
    def test_when_called_queries_by_id_with_the_bearer_token(self):
        reply = mock.MagicMock()
        reply.__enter__.return_value = reply
        reply.read.return_value = json.dumps(hardcover_response()).encode()

        with mock.patch("feeder.urllib.request.urlopen", return_value=reply) as urlopen:
            parsed = fetch_hardcover_book("175780", token="test-token")

        request = urlopen.call_args.args[0]
        assert request.full_url == HARDCOVER_URL
        assert request.get_header("Authorization") == "Bearer test-token"
        assert json.loads(request.data)["variables"] == {"id": 175780}
        assert parsed["publisher"] == "Scholastic Inc."
