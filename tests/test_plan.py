"""How the feeder decides which of Chaptarr's ebooks to feed.

A book is fed once: never when CWA's library already holds its Hardcover
ID, nor while a copy is in flight in the work or ingest folder.
"""

from feeder import plan_feed


def ebook(book_id, hardcover_id="hc:175780", has_files=True, media_type="ebook"):
    return {
        "id": book_id,
        "title": f"Book {book_id}",
        "hardcoverBookId": hardcover_id,
        "hasFiles": has_files,
        "mediaType": media_type,
    }


EPUB = "/data/media/books/ebooks/Suzanne Collins/Catching Fire/Catching Fire.epub"


class TestPlanFeed:
    def test_given_an_ebook_cwa_lacks_feeds_it_with_its_epub(self):
        book = ebook(1)

        to_feed, skipped = plan_feed([book], {1: EPUB}.get, present=set())

        assert to_feed == [(book, EPUB)]
        assert skipped == []

    def test_given_an_ebook_already_in_cwas_library_leaves_it(self):
        to_feed, skipped = plan_feed([ebook(1)], {1: EPUB}.get, present={"175780"})

        assert to_feed == []
        assert skipped == []

    def test_given_an_audiobook_record_ignores_it(self):
        to_feed, skipped = plan_feed(
            [ebook(1, media_type="audiobook")], {1: EPUB}.get, present=set()
        )

        assert to_feed == []
        assert skipped == []

    def test_given_an_ebook_with_no_files_ignores_it(self):
        to_feed, skipped = plan_feed([ebook(1, has_files=False)], {}.get, present=set())

        assert to_feed == []
        assert skipped == []

    def test_given_an_ebook_with_no_hardcover_id_skips_and_reports_it(self):
        book = ebook(1, hardcover_id=None)

        to_feed, skipped = plan_feed([book], {1: EPUB}.get, present=set())

        assert to_feed == []
        assert skipped == [(book, "no Hardcover ID")]

    def test_given_an_ebook_whose_only_file_is_not_an_epub_skips_and_reports_it(
        self,
    ):
        book = ebook(1)

        to_feed, skipped = plan_feed([book], {}.get, present=set())

        assert to_feed == []
        assert skipped == [(book, "no EPUB file")]
