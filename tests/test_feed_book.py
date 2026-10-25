"""How the feeder hands one book to CWA.

The library's file is copied, never moved or linked, since it may be
seeding a torrent. The copy reaches CWA's ingest folder only once its
metadata reads back correctly.
"""

import pytest

from feeder import Metadata, ReadBackMismatch, feed_book

METADATA = Metadata(
    title="Catching Fire",
    author="Suzanne Collins",
    hardcover_id="175780",
    series="The Hunger Games",
    series_index="2",
    description="Katniss has won the Hunger Games.",
    date="2009-09-01",
    tags=["Dystopian"],
    isbn="9781407133188",
    publisher="Scholastic",
)


def folders(tmp_path):
    epub = tmp_path / "library" / "Catching Fire.epub"
    epub.parent.mkdir()
    epub.write_bytes(b"epub bytes")
    work, ingest = tmp_path / "feeder", tmp_path / "ingest"
    work.mkdir()
    ingest.mkdir()
    return epub, work, ingest


class TestFeedBook:
    def test_when_the_metadata_reads_back_moves_the_copy_into_ingest(
        self, tmp_path, fake_ebook_meta
    ):
        epub, work, ingest = folders(tmp_path)

        gaps = feed_book(epub, METADATA, work, ingest, run=fake_ebook_meta())

        assert gaps == []
        assert (ingest / "hc-175780.epub").read_bytes() == b"epub bytes"
        assert list(work.iterdir()) == []

    def test_when_feeding_leaves_the_librarys_file_untouched(
        self, tmp_path, fake_ebook_meta
    ):
        epub, work, ingest = folders(tmp_path)

        feed_book(epub, METADATA, work, ingest, run=fake_ebook_meta())

        assert epub.read_bytes() == b"epub bytes"

    def test_when_writing_metadata_edits_the_copy_not_the_library_file(
        self, tmp_path, fake_ebook_meta
    ):
        epub, work, ingest = folders(tmp_path)
        ebook_meta = fake_ebook_meta()

        feed_book(epub, METADATA, work, ingest, run=ebook_meta)

        written = [str(args[1]) for args in ebook_meta.calls]
        assert written and all(path.startswith(str(work)) for path in written)

    def test_when_the_metadata_reads_back_wrong_discards_the_copy(
        self, tmp_path, fake_ebook_meta
    ):
        epub, work, ingest = folders(tmp_path)

        with pytest.raises(ReadBackMismatch) as mismatch:
            feed_book(
                epub,
                METADATA,
                work,
                ingest,
                run=fake_ebook_meta(misread={"title": "Wrong"}),
            )

        assert mismatch.value.fields == ["title"]
        assert list(ingest.iterdir()) == []
        assert list(work.iterdir()) == []

    def test_given_an_epub_without_a_cover_feeds_it_and_reports_the_cover(
        self, tmp_path, fake_ebook_meta
    ):
        epub, work, ingest = folders(tmp_path)

        gaps = feed_book(
            epub, METADATA, work, ingest, run=fake_ebook_meta(has_cover=False)
        )

        assert gaps == ["cover"]
        assert (ingest / "hc-175780.epub").exists()
