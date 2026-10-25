"""How the feeder builds a book's metadata, and which gaps hold it.

A missing title, author or description holds the book back from CWA;
any other missing field lets it through and is reported.
"""

from feeder import Metadata, build_metadata


def chaptarr_book(**overrides):
    book = {
        "id": 16112,
        "title": "Catching Fire",
        "author": {"authorName": "Suzanne Collins"},
        "seriesTitle": "The Hunger Games #2",
        "hardcoverBookId": "hc:175780",
        "releaseDate": "2010-06-03T00:00:00Z",
    }
    book.update(overrides)
    return book


def chaptarr_edition(**overrides):
    edition = {"isbn13": "9781407133188", "publisher": "Scholastic"}
    edition.update(overrides)
    return edition


def hardcover_book(**overrides):
    book = {
        "description": "Katniss and Peeta won the Games.",
        "release_date": "2009-09-01",
        "genres": ["Young Adult", "Dystopian", "Fiction", "Romance", "Action", "Teen"],
        "series": ("The Hunger Games", "2"),
        "isbn": "9780545227247",
        "publisher": "Scholastic Press",
    }
    book.update(overrides)
    return book


class TestBuildMetadata:
    def test_given_complete_sources_builds_every_field_with_no_gaps(self):
        metadata, held, gaps = build_metadata(
            chaptarr_book(), chaptarr_edition(), hardcover_book()
        )

        assert metadata == Metadata(
            title="Catching Fire",
            author="Suzanne Collins",
            hardcover_id="175780",
            series="The Hunger Games",
            series_index="2",
            description="Katniss and Peeta won the Games.",
            date="2009-09-01",
            tags=["Young Adult", "Dystopian", "Fiction", "Romance", "Action"],
            isbn="9781407133188",
            publisher="Scholastic",
        )
        assert held == []
        assert gaps == []

    def test_given_more_than_five_genres_keeps_hardcovers_top_five(self):
        metadata, _, _ = build_metadata(
            chaptarr_book(), chaptarr_edition(), hardcover_book()
        )

        assert len(metadata.tags) == 5

    def test_given_no_title_holds_the_book(self):
        _, held, _ = build_metadata(
            chaptarr_book(title=""), chaptarr_edition(), hardcover_book()
        )

        assert held == ["title"]

    def test_given_no_author_holds_the_book(self):
        _, held, _ = build_metadata(
            chaptarr_book(author={"authorName": None}),
            chaptarr_edition(),
            hardcover_book(),
        )

        assert held == ["author"]

    def test_given_no_hardcover_description_holds_the_book(self):
        _, held, _ = build_metadata(
            chaptarr_book(), chaptarr_edition(), hardcover_book(description=None)
        )

        assert held == ["description"]

    def test_when_hardcover_returned_nothing_holds_the_book_for_its_description(
        self,
    ):
        _, held, _ = build_metadata(chaptarr_book(), chaptarr_edition(), None)

        assert held == ["description"]

    def test_given_no_hardcover_date_falls_back_to_chaptarrs_release_date(self):
        metadata, _, gaps = build_metadata(
            chaptarr_book(), chaptarr_edition(), hardcover_book(release_date=None)
        )

        assert metadata.date == "2010-06-03"
        assert gaps == []

    def test_given_no_date_anywhere_reports_the_date(self):
        _, held, gaps = build_metadata(
            chaptarr_book(releaseDate=None),
            chaptarr_edition(),
            hardcover_book(release_date=None),
        )

        assert held == []
        assert gaps == ["date"]

    def test_given_no_genres_reports_the_tags(self):
        _, held, gaps = build_metadata(
            chaptarr_book(), chaptarr_edition(), hardcover_book(genres=[])
        )

        assert held == []
        assert gaps == ["tags"]

    def test_given_an_edition_without_isbn_or_publisher_falls_back_to_hardcover(
        self,
    ):
        metadata, _, gaps = build_metadata(
            chaptarr_book(),
            chaptarr_edition(isbn13=None, publisher=None),
            hardcover_book(),
        )

        assert metadata.isbn == "9780545227247"
        assert metadata.publisher == "Scholastic Press"
        assert gaps == []

    def test_given_no_isbn_or_publisher_anywhere_reports_both(self):
        _, held, gaps = build_metadata(
            chaptarr_book(), None, hardcover_book(isbn=None, publisher=None)
        )

        assert held == []
        assert gaps == ["isbn", "publisher"]

    def test_given_no_series_in_either_source_reports_nothing(self):
        metadata, _, gaps = build_metadata(
            chaptarr_book(seriesTitle=None),
            chaptarr_edition(),
            hardcover_book(series=None),
        )

        assert (metadata.series, metadata.series_index) == (None, None)
        assert gaps == []

    def test_given_a_series_only_hardcover_lists_reports_the_series(self):
        metadata, held, gaps = build_metadata(
            chaptarr_book(seriesTitle=None), chaptarr_edition(), hardcover_book()
        )

        assert metadata.series is None
        assert held == []
        assert gaps == ["series"]
