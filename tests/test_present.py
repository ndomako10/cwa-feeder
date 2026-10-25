"""How the feeder knows which books CWA already has or is about to get.

The identifiers table matches Calibre 9.1's `metadata.db` in CWA's library
(2026-10-20).
"""

import sqlite3

from feeder import in_flight_ids, library_hardcover_ids


def calibre_library(path, identifiers):
    db = sqlite3.connect(path)
    db.execute(
        """CREATE TABLE identifiers (
            id INTEGER PRIMARY KEY,
            book INTEGER NOT NULL,
            type TEXT NOT NULL DEFAULT "isbn" COLLATE NOCASE,
            val TEXT NOT NULL COLLATE NOCASE,
            UNIQUE(book, type))"""
    )
    db.executemany(
        "INSERT INTO identifiers (book, type, val) VALUES (?, ?, ?)", identifiers
    )
    db.commit()
    db.close()


class TestLibraryHardcoverIds:
    def test_given_books_with_hardcover_ids_returns_those_ids(self, tmp_path):
        db = tmp_path / "metadata.db"
        calibre_library(
            db,
            [(1, "hardcover-id", "175780"), (1, "isbn", "9780545227247")],
        )

        assert library_hardcover_ids(db) == {"175780"}

    def test_given_the_type_in_another_case_still_finds_it(self, tmp_path):
        db = tmp_path / "metadata.db"
        calibre_library(db, [(1, "HARDCOVER-ID", "175780")])

        assert library_hardcover_ids(db) == {"175780"}


class TestInFlightIds:
    def test_given_fed_files_waiting_in_ingest_returns_their_ids(self, tmp_path):
        (tmp_path / "hc-175780.epub").touch()
        (tmp_path / "hc-12.epub").touch()

        assert in_flight_ids(tmp_path) == {"175780", "12"}

    def test_given_files_the_feeder_did_not_name_ignores_them(self, tmp_path):
        (tmp_path / "Catching Fire.epub").touch()
        (tmp_path / "hc-175780.epub.tmp").touch()

        assert in_flight_ids(tmp_path) == set()
