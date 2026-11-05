"""How one feeder run reconciles Chaptarr's ebooks with CWA.

Chaptarr and Hardcover are faked with the shapes their APIs gave on
2026-10-20; the Calibre library is a real SQLite file.
"""

import json
import sqlite3

from feeder import HardcoverError, Settings, run_once

EPUB_DIR = "Suzanne Collins/The Hunger Games/2 - Catching Fire"


def chaptarr_api(tmp_path, books):
    """Fake Chaptarr's API for ``books``, each an (id, title, hardcover id)."""
    responses = {"/api/v1/book": []}
    for book_id, title, hardcover_id in books:
        record = {
            "id": book_id,
            "title": title,
            "mediaType": "ebook",
            "hasFiles": True,
            "hardcoverBookId": hardcover_id and f"hc:{hardcover_id}",
            "seriesTitle": "The Hunger Games #2",
            "releaseDate": "2010-06-03T00:00:00Z",
        }
        responses["/api/v1/book"].append(record)
        responses[f"/api/v1/book/{book_id}"] = {
            **record,
            "author": {"authorName": "Suzanne Collins"},
        }
        epub = tmp_path / "ebooks" / EPUB_DIR / f"{title}.epub"
        epub.parent.mkdir(parents=True, exist_ok=True)
        epub.write_bytes(b"epub bytes")
        responses[f"/api/v1/bookfile?bookId={book_id}"] = [
            {"bookId": book_id, "path": str(epub.with_suffix(".mobi"))},
            {"bookId": book_id, "path": str(epub)},
        ]
        responses[f"/api/v1/edition?bookId={book_id}"] = [
            {"isbn13": None, "publisher": "Scholastic Inc.", "monitored": False},
            {"isbn13": "9781407133188", "publisher": "Scholastic", "monitored": True},
        ]
    calls = []

    def get(path):
        calls.append(path)
        return responses[path]

    get.calls = calls
    get.responses = responses
    return get


def hardcover_api(books=None, error=None):
    def fetch(hardcover_id):
        if error:
            raise error
        return (books or {}).get(hardcover_id)

    return fetch


def hardcover_book(**overrides):
    book = {
        "description": "Katniss has won the Hunger Games.",
        "release_date": "2009-09-01",
        "genres": ["Dystopian", "Young Adult"],
        "series": ("The Hunger Games", "2"),
        "isbn": "9780545227247",
        "publisher": "Scholastic Inc.",
    }
    book.update(overrides)
    return book


def settings(tmp_path, library_ids=()):
    root = tmp_path / "calibre"
    for folder in ("library", "ingest", "feeder"):
        (root / folder).mkdir(parents=True)
    db = sqlite3.connect(root / "library" / "metadata.db")
    db.execute(
        "CREATE TABLE identifiers (id INTEGER PRIMARY KEY, book INTEGER, "
        "type TEXT COLLATE NOCASE, val TEXT)"
    )
    db.executemany(
        "INSERT INTO identifiers (book, type, val) VALUES (?, 'hardcover-id', ?)",
        enumerate(library_ids),
    )
    db.execute("CREATE TABLE books (id INTEGER PRIMARY KEY, title TEXT)")
    db.commit()
    db.close()
    return Settings(
        library_db=root / "library" / "metadata.db",
        ingest_dir=root / "ingest",
        work_dir=root / "feeder" / "work",
        report_path=root / "feeder" / "report.json",
    )


def add_to_library(config, hardcover_id):
    db = sqlite3.connect(config.library_db)
    db.execute(
        "INSERT INTO identifiers (book, type, val) VALUES (99, 'hardcover-id', ?)",
        (hardcover_id,),
    )
    db.commit()
    db.close()


def ingested(config):
    return sorted(path.name for path in config.ingest_dir.iterdir())


class TestRunOnce:
    def test_given_a_book_cwa_lacks_feeds_it_and_reports_nothing(
        self, tmp_path, fake_ebook_meta
    ):
        config = settings(tmp_path)
        chaptarr = chaptarr_api(tmp_path, [(16112, "Catching Fire", "175780")])
        ebook_meta = fake_ebook_meta()

        report = run_once(
            config,
            chaptarr,
            hardcover_api({"175780": hardcover_book()}),
            run=ebook_meta,
            goodreads={}.get,
        )

        assert ingested(config) == ["hc-175780.epub"]
        assert ebook_meta.written["--isbn"] == "9781407133188"
        assert report == {
            "incomplete": [],
            "held": [],
            "skipped": [],
            "failed": [],
            "waiting": [],
            "in_cwa_without_id": [],
        }

    def test_given_a_book_already_in_cwa_looks_nothing_up(
        self, tmp_path, fake_ebook_meta
    ):
        config = settings(tmp_path, library_ids=["175780"])
        chaptarr = chaptarr_api(tmp_path, [(16112, "Catching Fire", "175780")])

        run_once(
            config, chaptarr, hardcover_api(), run=fake_ebook_meta(), goodreads={}.get
        )

        assert ingested(config) == []
        assert chaptarr.calls == ["/api/v1/book"]

    def test_given_a_book_waiting_in_ingest_doesnt_feed_it_again(
        self, tmp_path, fake_ebook_meta
    ):
        config = settings(tmp_path)
        (config.ingest_dir / "hc-175780.epub").write_bytes(b"earlier copy")
        chaptarr = chaptarr_api(tmp_path, [(16112, "Catching Fire", "175780")])

        report = run_once(
            config, chaptarr, hardcover_api(), run=fake_ebook_meta(), goodreads={}.get
        )

        assert (config.ingest_dir / "hc-175780.epub").read_bytes() == b"earlier copy"
        assert report["waiting"] == ["175780"]

    def test_given_no_hardcover_description_holds_the_book_and_reports_it(
        self, tmp_path, fake_ebook_meta
    ):
        config = settings(tmp_path)
        chaptarr = chaptarr_api(tmp_path, [(16112, "Catching Fire", "175780")])
        hardcover = hardcover_api({"175780": hardcover_book(description=None)})

        report = run_once(
            config, chaptarr, hardcover, run=fake_ebook_meta(), goodreads={}.get
        )

        assert ingested(config) == []
        assert report["held"] == [
            {
                "hardcover_id": "175780",
                "title": "Catching Fire",
                "missing": ["description"],
            }
        ]

    def test_given_a_metadata_read_back_mismatch_holds_the_book(
        self, tmp_path, fake_ebook_meta
    ):
        config = settings(tmp_path)
        chaptarr = chaptarr_api(tmp_path, [(16112, "Catching Fire", "175780")])
        hardcover = hardcover_api({"175780": hardcover_book()})

        report = run_once(
            config,
            chaptarr,
            hardcover,
            run=fake_ebook_meta(misread={"title": "X"}),
            goodreads={}.get,
        )

        assert ingested(config) == []
        assert report["held"] == [
            {
                "hardcover_id": "175780",
                "title": "Catching Fire",
                "read_back_wrong": ["title"],
            }
        ]

    def test_given_gaps_that_dont_hold_a_book_feeds_it_and_keeps_reporting_them(
        self, tmp_path, fake_ebook_meta
    ):
        config = settings(tmp_path)
        chaptarr = chaptarr_api(tmp_path, [(16112, "Catching Fire", "175780")])
        hardcover = hardcover_api({"175780": hardcover_book(genres=[])})
        incomplete = {
            "hardcover_id": "175780",
            "title": "Catching Fire",
            "missing": ["tags", "cover"],
        }

        first = run_once(
            config,
            chaptarr,
            hardcover,
            run=fake_ebook_meta(has_cover=False),
            goodreads={}.get,
        )
        (config.ingest_dir / "hc-175780.epub").unlink()
        add_to_library(config, "175780")
        second = run_once(
            config, chaptarr, hardcover, run=fake_ebook_meta(), goodreads={}.get
        )

        assert first["incomplete"] == [incomplete]
        assert second["incomplete"] == [incomplete]

    def test_given_a_book_with_no_hardcover_id_skips_and_reports_it(
        self, tmp_path, fake_ebook_meta
    ):
        config = settings(tmp_path)
        chaptarr = chaptarr_api(tmp_path, [(16112, "Catching Fire", None)])

        report = run_once(
            config, chaptarr, hardcover_api(), run=fake_ebook_meta(), goodreads={}.get
        )

        assert report["skipped"] == [
            {
                "chaptarr_id": 16112,
                "title": "Catching Fire",
                "reason": "no Hardcover ID",
            }
        ]

    def test_when_one_book_fails_still_feeds_the_others(
        self, tmp_path, fake_ebook_meta
    ):
        config = settings(tmp_path)
        chaptarr = chaptarr_api(
            tmp_path,
            [(16112, "Catching Fire", "175780"), (16115, "Mockingjay", "175781")],
        )

        def hardcover(hardcover_id):
            if hardcover_id == "175780":
                raise HardcoverError("rate limited")
            return hardcover_book()

        report = run_once(
            config, chaptarr, hardcover, run=fake_ebook_meta(), goodreads={}.get
        )

        assert ingested(config) == ["hc-175781.epub"]
        assert report["failed"] == [
            {
                "hardcover_id": "175780",
                "title": "Catching Fire",
                "error": "HardcoverError: rate limited",
            }
        ]

    def test_given_leftovers_from_an_interrupted_run_clears_them_first(
        self, tmp_path, fake_ebook_meta
    ):
        config = settings(tmp_path)
        config.work_dir.mkdir()
        (config.work_dir / "hc-175780.epub").write_bytes(b"half written")
        chaptarr = chaptarr_api(tmp_path, [])

        run_once(
            config, chaptarr, hardcover_api(), run=fake_ebook_meta(), goodreads={}.get
        )

        assert list(config.work_dir.iterdir()) == []

    def test_when_done_writes_the_report_to_disk(self, tmp_path, fake_ebook_meta):
        config = settings(tmp_path)
        chaptarr = chaptarr_api(tmp_path, [(16112, "Catching Fire", None)])

        report = run_once(
            config, chaptarr, hardcover_api(), run=fake_ebook_meta(), goodreads={}.get
        )

        assert json.loads(config.report_path.read_text(encoding="utf-8")) == report


def on_goodreads_record(chaptarr, book_id, edition="gr:56791389-ebook"):
    """Make a faked book one Chaptarr holds under a Goodreads record."""
    for record in (
        next(b for b in chaptarr.responses["/api/v1/book"] if b["id"] == book_id),
        chaptarr.responses[f"/api/v1/book/{book_id}"],
    ):
        record["hardcoverBookId"] = None
        record["foreignEditionId"] = edition


class TestRunOnceWithAGoodreadsRecord:
    def test_given_hardcover_maps_its_edition_feeds_it_under_that_id(
        self, tmp_path, fake_ebook_meta
    ):
        config = settings(tmp_path)
        chaptarr = chaptarr_api(tmp_path, [(2097, "Dungeon Crawler Carl", None)])
        on_goodreads_record(chaptarr, 2097)
        ebook_meta = fake_ebook_meta()

        report = run_once(
            config,
            chaptarr,
            hardcover_api({"446681": hardcover_book()}),
            run=ebook_meta,
            goodreads={"56791389": "446681"}.get,
        )

        assert ingested(config) == ["hc-446681.epub"]
        assert ebook_meta.written["--identifier"] == "hardcover-id:446681"
        assert ebook_meta.written["--series"] == "The Hunger Games"
        assert report["skipped"] == []

    def test_given_its_mapped_book_is_already_in_cwa_doesnt_feed_it_again(
        self, tmp_path, fake_ebook_meta
    ):
        config = settings(tmp_path, library_ids=["446681"])
        chaptarr = chaptarr_api(tmp_path, [(2097, "Dungeon Crawler Carl", None)])
        on_goodreads_record(chaptarr, 2097)

        report = run_once(
            config,
            chaptarr,
            hardcover_api(),
            run=fake_ebook_meta(),
            goodreads={"56791389": "446681"}.get,
        )

        assert ingested(config) == []
        assert report["skipped"] == []

    def test_given_hardcover_has_no_mapping_skips_and_reports_it(
        self, tmp_path, fake_ebook_meta
    ):
        config = settings(tmp_path)
        chaptarr = chaptarr_api(tmp_path, [(2097, "Dungeon Crawler Carl", None)])
        on_goodreads_record(chaptarr, 2097)

        report = run_once(
            config, chaptarr, hardcover_api(), run=fake_ebook_meta(), goodreads={}.get
        )

        assert ingested(config) == []
        assert report["skipped"] == [
            {
                "chaptarr_id": 2097,
                "title": "Dungeon Crawler Carl",
                "reason": "no Hardcover ID",
            }
        ]

    def test_when_the_lookup_fails_reports_it_and_still_feeds_the_others(
        self, tmp_path, fake_ebook_meta
    ):
        config = settings(tmp_path)
        chaptarr = chaptarr_api(
            tmp_path,
            [(2097, "Dungeon Crawler Carl", None), (16112, "Catching Fire", "175780")],
        )
        on_goodreads_record(chaptarr, 2097)

        def lookup(_edition):
            raise HardcoverError("invalid token")

        report = run_once(
            config,
            chaptarr,
            hardcover_api({"175780": hardcover_book()}),
            run=fake_ebook_meta(),
            goodreads=lookup,
        )

        assert ingested(config) == ["hc-175780.epub"]
        assert report["skipped"] == []
        assert report["failed"] == [
            {
                "chaptarr_id": 2097,
                "title": "Dungeon Crawler Carl",
                "error": "HardcoverError: invalid token",
            }
        ]

    def test_given_a_record_with_no_files_never_looks_it_up(
        self, tmp_path, fake_ebook_meta
    ):
        config = settings(tmp_path)
        chaptarr = chaptarr_api(tmp_path, [(2097, "Dungeon Crawler Carl", None)])
        on_goodreads_record(chaptarr, 2097)
        chaptarr.responses["/api/v1/book"][0]["hasFiles"] = False

        def lookup(_edition):
            raise AssertionError("looked up a book with no files")

        run_once(
            config, chaptarr, hardcover_api(), run=fake_ebook_meta(), goodreads=lookup
        )


class TestRunOnceWithABookAddedToCwaByHand:
    def test_given_a_library_book_with_no_hardcover_id_reports_it(
        self, tmp_path, fake_ebook_meta
    ):
        config = settings(tmp_path, library_ids=["175780"])
        db = sqlite3.connect(config.library_db)
        db.execute("INSERT INTO books (id, title) VALUES (0, 'Catching Fire')")
        db.execute("INSERT INTO books (id, title) VALUES (7, 'Mockingjay')")
        db.commit()
        db.close()

        report = run_once(
            config,
            chaptarr_api(tmp_path, []),
            hardcover_api(),
            run=fake_ebook_meta(),
            goodreads={}.get,
        )

        assert report["in_cwa_without_id"] == [{"calibre_id": 7, "title": "Mockingjay"}]
