"""Feed Chaptarr's ebooks into Calibre-Web Automated with complete metadata.

See README.md for how it works and how to run it.
"""

import functools
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger("cwa-feeder")


# Chaptarr's API gives an ebook's series as one string, "Name #N", where N
# may be fractional (a novella between books, e.g. #2.5).
SERIES_WITH_NUMBER = re.compile(r"^(?P<name>.+) #(?P<number>\d+(?:\.\d+)?)$")


def parse_series(series_title: str | None) -> tuple[str, str | None] | None:
    """Split Chaptarr's "Name #N" into the series name and its number."""
    if not series_title:
        return None
    match = SERIES_WITH_NUMBER.match(series_title)
    if not match:
        return series_title, None
    return match["name"], match["number"]


# Chaptarr prefixes each ID with its source ("hc:175780"); CWA's identifier
# holds the bare number.
HARDCOVER_PREFIX = "hc:"


def hardcover_id_of(book: dict) -> str | None:
    """Read a Chaptarr book's Hardcover ID as the bare number."""
    return (book.get("hardcoverBookId") or "").removeprefix(HARDCOVER_PREFIX) or None


# Hardcover ranks a book's genres by how many readers tagged them; past the
# first few they turn into noise ("Audiobook", "teen").
TOP_GENRES = 5


@dataclass
class Metadata:
    title: str | None
    author: str | None
    hardcover_id: str | None
    series: str | None
    series_index: str | None
    description: str | None
    date: str | None
    tags: list[str]
    isbn: str | None
    publisher: str | None


def build_metadata(
    book: dict, edition: dict | None, hardcover: dict | None
) -> tuple[Metadata, list[str], list[str]]:
    """Merge Chaptarr's and Hardcover's records into one book's metadata.

    Returns the metadata, the missing fields that hold the book back from CWA,
    and the missing fields that only get reported.
    """
    edition = edition or {}
    hardcover = hardcover or {}
    series, series_index = parse_series(book.get("seriesTitle")) or (None, None)
    release_date = book.get("releaseDate")
    metadata = Metadata(
        title=book.get("title") or None,
        author=(book.get("author") or {}).get("authorName") or None,
        hardcover_id=hardcover_id_of(book),
        series=series,
        series_index=series_index,
        description=hardcover.get("description") or None,
        date=hardcover.get("release_date")
        or (release_date[:10] if release_date else None),
        tags=(hardcover.get("genres") or [])[:TOP_GENRES],
        isbn=edition.get("isbn13") or hardcover.get("isbn") or None,
        publisher=edition.get("publisher") or hardcover.get("publisher") or None,
    )
    held = [
        field
        for field in ("title", "author", "description")
        if not getattr(metadata, field)
    ]
    gaps = [
        field
        for field in ("date", "tags", "isbn", "publisher")
        if not getattr(metadata, field)
    ]
    if metadata.series is None and hardcover.get("series"):
        gaps.append("series")
    return metadata, held, gaps


def plan_feed(
    books: list[dict],
    epub_for: Callable[[int], str | None],
    present: set[str],
) -> tuple[list[tuple[dict, str]], list[tuple[dict, str]]]:
    """Pick the ebooks to feed, and those that can't be fed and why.

    ``epub_for`` gives a Chaptarr book's EPUB path; it is asked only about books
    still to feed, since each answer costs an API call. ``present`` holds the
    Hardcover IDs already in CWA's library or in flight to it.
    """
    to_feed, skipped = [], []
    for book in books:
        if book.get("mediaType") != "ebook" or not book.get("hasFiles"):
            continue
        hardcover_id = hardcover_id_of(book)
        if not hardcover_id:
            skipped.append((book, "no Hardcover ID"))
        elif hardcover_id in present:
            continue
        elif epub := epub_for(book["id"]):
            to_feed.append((book, epub))
        else:
            skipped.append((book, "no EPUB file"))
    return to_feed, skipped


# Found on PATH: the feeder's image puts Calibre's command-line tools there.
EBOOK_META = "ebook-meta"

# Calibre splits --tags on commas and has no escape for one inside a tag.
TAG_SEPARATOR = ","

OPF_NAMESPACES = {
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
}
OPF_SCHEME = "{http://www.idpf.org/2007/opf}scheme"


def ebook_meta_args(path: str, metadata: Metadata) -> list[str]:
    """Build the ebook-meta command that writes every known field into ``path``.

    A field with no value is left out, so the file keeps its own.
    """
    options = {
        "--title": metadata.title,
        "--authors": metadata.author,
        "--identifier": metadata.hardcover_id
        and f"hardcover-id:{metadata.hardcover_id}",
        "--series": metadata.series,
        "--index": metadata.series_index,
        "--comments": metadata.description,
        "--date": metadata.date,
        "--tags": TAG_SEPARATOR.join(
            tag.replace(TAG_SEPARATOR, ";") for tag in metadata.tags
        ),
        "--isbn": metadata.isbn,
        "--publisher": metadata.publisher,
    }
    args = [EBOOK_META, path]
    for option, value in options.items():
        if value:
            args += [option, value]
    return args


def verify_opf(opf_xml: str, metadata: Metadata) -> list[str]:
    """List the fields an EPUB's OPF (from ``ebook-meta --to-opf``) got wrong.

    Checks the fields that decide where CWA files the book. The description
    only has to be there, since Calibre may reflow its markup.
    """
    root = ET.fromstring(opf_xml).find("opf:metadata", OPF_NAMESPACES)

    def text(tag: str) -> str | None:
        element = root.find(tag, OPF_NAMESPACES)
        return element.text if element is not None else None

    def meta(name: str) -> str | None:
        element = root.find(f"opf:meta[@name='{name}']", OPF_NAMESPACES)
        return element.get("content") if element is not None else None

    hardcover_ids = [
        element.text
        for element in root.findall("dc:identifier", OPF_NAMESPACES)
        if (element.get(OPF_SCHEME) or "").lower() == "hardcover-id"
    ]
    index = meta("calibre:series_index")
    found = {
        "title": text("dc:title") == metadata.title,
        "author": text("dc:creator") == metadata.author,
        "hardcover_id": hardcover_ids == [metadata.hardcover_id],
        "series": metadata.series is None or meta("calibre:series") == metadata.series,
        "series_index": metadata.series_index is None
        or (index is not None and float(index) == float(metadata.series_index)),
        "description": bool(text("dc:description")),
    }
    return [field for field, matches in found.items() if not matches]


HARDCOVER_URL = "https://api.hardcover.app/v1/graphql"
HARDCOVER_QUERY = """
query ($id: Int!) {
  books(where: {id: {_eq: $id}}) {
    description
    release_date
    cached_tags
    book_series { position series { name } }
    default_ebook_edition { isbn_13 publisher { name } }
    default_physical_edition { isbn_13 publisher { name } }
  }
}
"""
HTTP_TIMEOUT_SECONDS = 30


class HardcoverError(Exception):
    """Hardcover answered, but with an error instead of data."""


def parse_hardcover_book(response: dict) -> dict | None:
    """Reduce Hardcover's GraphQL reply to the fields ``build_metadata`` takes."""
    if "errors" in response:
        raise HardcoverError("; ".join(e["message"] for e in response["errors"]))
    books = response["data"]["books"]
    if not books:
        return None
    book = books[0]
    series = None
    if book.get("book_series"):
        entry = book["book_series"][0]
        position = entry.get("position")
        series = (
            entry["series"]["name"],
            f"{position:g}" if position is not None else None,
        )
    edition = book.get("default_ebook_edition") or {}
    print_edition = book.get("default_physical_edition") or {}
    publisher = edition.get("publisher") or print_edition.get("publisher") or {}
    return {
        "description": book.get("description"),
        "release_date": book.get("release_date"),
        "genres": [
            tag["tag"] for tag in (book.get("cached_tags") or {}).get("Genre", [])
        ],
        "series": series,
        "isbn": edition.get("isbn_13") or print_edition.get("isbn_13"),
        "publisher": publisher.get("name"),
    }


def fetch_hardcover_book(hardcover_id: str, token: str) -> dict | None:
    """Look a book up on Hardcover by its ID."""
    request = urllib.request.Request(
        HARDCOVER_URL,
        data=json.dumps(
            {"query": HARDCOVER_QUERY, "variables": {"id": int(hardcover_id)}}
        ).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "cwa-feeder",
        },
    )
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as reply:
        return parse_hardcover_book(json.loads(reply.read()))


# The feeder names each file it copies by the book's Hardcover ID, so a file
# waiting in CWA's ingest folder says which book it is without being opened.
FED_FILE = re.compile(r"^hc-(?P<id>\d+)\.epub$")


def library_hardcover_ids(metadata_db: Path) -> set[str]:
    """Read the Hardcover IDs in CWA's Calibre library, without locking it."""
    db = sqlite3.connect(f"file:{metadata_db}?mode=ro", uri=True)
    try:
        rows = db.execute(
            "SELECT val FROM identifiers WHERE type = 'hardcover-id'"
        ).fetchall()
    finally:
        db.close()
    return {val for (val,) in rows}


def in_flight_ids(ingest_dir: Path) -> set[str]:
    """Read the Hardcover IDs of fed files that CWA hasn't imported yet."""
    return {
        match["id"]
        for path in ingest_dir.iterdir()
        if (match := FED_FILE.match(path.name))
    }


class ReadBackMismatch(Exception):
    """The metadata read back from a copy differs from what was written."""

    def __init__(self, fields: list[str]):
        super().__init__(f"read back wrong: {', '.join(fields)}")
        self.fields = fields


def feed_book(
    epub: Path,
    metadata: Metadata,
    work_dir: Path,
    ingest_dir: Path,
    run: Callable[..., object] = subprocess.run,
) -> list[str]:
    """Copy one ebook, write its metadata, check it, and hand it to CWA.

    Returns the fields that are missing but don't hold the book (its cover).
    Raises ReadBackMismatch, leaving nothing behind, if the copy's metadata
    isn't what was written.
    """
    name = f"hc-{metadata.hardcover_id}"
    copy, opf, cover = (work_dir / f"{name}{ext}" for ext in (".epub", ".opf", ".jpg"))
    shutil.copyfile(epub, copy)
    try:
        quietly = {"check": True, "capture_output": True}
        run(ebook_meta_args(str(copy), metadata), **quietly)
        run([EBOOK_META, str(copy), "--to-opf", str(opf)], **quietly)
        run([EBOOK_META, str(copy), f"--get-cover={cover}"], **quietly)
        mismatched = verify_opf(opf.read_text(encoding="utf-8"), metadata)
        if mismatched:
            raise ReadBackMismatch(mismatched)
        gaps = [] if cover.exists() else ["cover"]
        # Same mount as the ingest folder, so a rename: CWA never sees a
        # partial file.
        os.replace(copy, ingest_dir / copy.name)
        return gaps
    finally:
        for leftover in (copy, opf, cover):
            leftover.unlink(missing_ok=True)


@dataclass
class Settings:
    library_db: Path
    ingest_dir: Path
    work_dir: Path
    report_path: Path


def run_once(
    settings: Settings,
    chaptarr: Callable[[str], object],
    hardcover: Callable[[str], dict | None],
    run: Callable[..., object] = subprocess.run,
) -> dict:
    """Feed CWA every Chaptarr ebook it lacks, then rewrite the report.

    ``chaptarr`` GETs a path from Chaptarr's API; ``hardcover`` looks a book up
    by its Hardcover ID.
    """
    # Only the feeder writes here, and anything left behind is from a run that
    # was interrupted, so it's safe to clear and redo.
    shutil.rmtree(settings.work_dir, ignore_errors=True)
    settings.work_dir.mkdir(parents=True)

    waiting = in_flight_ids(settings.ingest_dir)
    present = library_hardcover_ids(settings.library_db) | waiting

    def epub_for(book_id: int) -> str | None:
        files = chaptarr(f"/api/v1/bookfile?bookId={book_id}")
        return next(
            (f["path"] for f in files if f["path"].lower().endswith(".epub")), None
        )

    to_feed, skipped = plan_feed(chaptarr("/api/v1/book"), epub_for, present)

    report = {
        "incomplete": [
            entry
            for entry in previous_incomplete(settings.report_path)
            if entry["hardcover_id"] in present
        ],
        "held": [],
        "skipped": [
            {"chaptarr_id": book["id"], "title": book["title"], "reason": reason}
            for book, reason in skipped
        ],
        "failed": [],
        "waiting": sorted(waiting),
    }
    for book, epub in to_feed:
        entry = {
            "hardcover_id": hardcover_id_of(book),
            "title": book["title"],
        }
        try:
            record = chaptarr(f"/api/v1/book/{book['id']}")
            editions = chaptarr(f"/api/v1/edition?bookId={book['id']}")
            edition = next((e for e in editions if e.get("monitored")), None)
            metadata, held, gaps = build_metadata(
                record, edition, hardcover(entry["hardcover_id"])
            )
            if held:
                report["held"].append({**entry, "missing": held})
                event(logging.WARNING, "held", **entry, missing=held)
                continue
            gaps += feed_book(
                Path(epub), metadata, settings.work_dir, settings.ingest_dir, run
            )
        except ReadBackMismatch as mismatch:
            report["held"].append({**entry, "read_back_wrong": mismatch.fields})
            event(logging.WARNING, "held", **entry, read_back_wrong=mismatch.fields)
            continue
        except Exception as error:  # one bad book mustn't stop the rest
            failure = f"{type(error).__name__}: {error}"
            report["failed"].append({**entry, "error": failure})
            event(logging.ERROR, "failed", **entry, error=failure)
            continue
        event(logging.INFO, "fed", **entry, missing=gaps)
        if gaps:
            report["incomplete"].append({**entry, "missing": gaps})

    # The report is also the only record of which fed books have gaps, so it
    # is replaced whole: a run cut short never leaves half a file.
    partial = settings.report_path.with_suffix(".json.tmp")
    partial.write_text(json.dumps(report, indent=2), encoding="utf-8", newline="\n")
    os.replace(partial, settings.report_path)
    return report


def previous_incomplete(report_path: Path) -> list[dict]:
    """Read the books fed with gaps, which only the last report remembers."""
    try:
        return json.loads(report_path.read_text(encoding="utf-8"))["incomplete"]
    except FileNotFoundError:
        return []


def event(level: int, name: str, **fields: object) -> None:
    """Log one event, with its fields as JSON keys."""
    log.log(level, name, extra={"fields": fields})


class JsonFormatter(logging.Formatter):
    """One JSON object per line, for central logging to parse."""

    def format(self, record: logging.LogRecord) -> str:
        line = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname.lower(),
            "event": record.getMessage(),
            **getattr(record, "fields", {}),
        }
        if record.exc_info:
            line["error"] = self.formatException(record.exc_info)
        return json.dumps(line)


def chaptarr_client(base_url: str, api_key: str) -> Callable[[str], object]:
    """Return a function that GETs a path from Chaptarr's API."""

    def get(path: str) -> object:
        request = urllib.request.Request(
            base_url.rstrip("/") + path, headers={"X-Api-Key": api_key}
        )
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as reply:
            return json.loads(reply.read())

    return get


# The feeder mounts CWA's data folder once at /calibre, so its work folder and
# CWA's ingest folder share a mount and the hand-over is a rename.
CALIBRE_ROOT = Path("/calibre")
DEFAULT_INTERVAL_SECONDS = 300


def settings_from_env(env: dict[str, str]) -> tuple[Settings, dict]:
    """Read the feeder's settings and secrets from its environment."""
    missing = [
        name
        for name in ("CHAPTARR_URL", "CHAPTARR_API_KEY", "HARDCOVER_TOKEN")
        if not env.get(name)
    ]
    if missing:
        raise SystemExit(f"missing environment variables: {', '.join(missing)}")
    settings = Settings(
        library_db=CALIBRE_ROOT / "library" / "metadata.db",
        ingest_dir=CALIBRE_ROOT / "ingest",
        work_dir=CALIBRE_ROOT / "feeder" / "work",
        report_path=CALIBRE_ROOT / "feeder" / "report.json",
    )
    config = {
        "chaptarr_url": env["CHAPTARR_URL"],
        "chaptarr_api_key": env["CHAPTARR_API_KEY"],
        # Hardcover's settings page shows the token with its "Bearer " prefix.
        "hardcover_token": env["HARDCOVER_TOKEN"].removeprefix("Bearer ").strip(),
        "interval_seconds": int(
            env.get("FEED_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS)
        ),
    }
    return settings, config


def serve(
    run: Callable[[], dict],
    interval_seconds: int,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Run the feeder forever; a failed run is logged and tried again later."""
    while True:
        try:
            report = run()
            event(
                logging.INFO,
                "run finished",
                **{status: len(books) for status, books in report.items()},
            )
        except Exception:
            log.exception("run failed")
        sleep(interval_seconds)


def main() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    settings, config = settings_from_env(dict(os.environ))
    chaptarr = chaptarr_client(config["chaptarr_url"], config["chaptarr_api_key"])
    hardcover = functools.partial(fetch_hardcover_book, token=config["hardcover_token"])
    serve(lambda: run_once(settings, chaptarr, hardcover), config["interval_seconds"])


if __name__ == "__main__":
    main()
