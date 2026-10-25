"""The feeder's image, tested from outside with the real Calibre.

Skipped unless CWA_FEEDER_IMAGE names a built image, so the unit suite
runs without Docker:

    docker build -t cwa-feeder:dev .
    CWA_FEEDER_IMAGE=cwa-feeder:dev pytest tests/test_image.py

Every container runs with the restrictions the README recommends.
"""

import base64
import json
import os
import subprocess
import zipfile
from pathlib import Path

import pytest

IMAGE = os.environ.get("CWA_FEEDER_IMAGE")
pytestmark = pytest.mark.skipif(not IMAGE, reason="CWA_FEEDER_IMAGE is not set")

HARDENED = [
    "--rm",
    "--read-only",
    "--tmpfs",
    "/tmp",
    "--cap-drop",
    "ALL",
    "--security-opt",
    "no-new-privileges:true",
]

METADATA = {
    "title": "Catching Fire",
    "author": "Suzanne Collins",
    "hardcover_id": "175780",
    "series": "The Hunger Games",
    "series_index": "2",
    "description": "Sparks are igniting.",
    "date": "2009-09-01",
    "tags": ["Young Adult", "Dystopian"],
    "isbn": "9780439023498",
    "publisher": "Scholastic",
}

ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def write_epub(path: Path) -> None:
    """Write the smallest EPUB 2 that Calibre treats as a book with a cover."""
    opf = (
        '<?xml version="1.0"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="2.0" '
        'unique-identifier="id">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<dc:title>Old title</dc:title><dc:identifier id="id">test</dc:identifier>'
        '<dc:language>en</dc:language><meta name="cover" content="cover"/></metadata>'
        '<manifest><item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="cover" href="cover.png" media-type="image/png"/>'
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
        "</manifest>"
        '<spine toc="ncx"><itemref idref="c1"/></spine></package>'
    )
    with zipfile.ZipFile(path, "w") as epub:
        epub.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip")
        epub.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container version="1.0" '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
            '<rootfile full-path="content.opf" '
            'media-type="application/oebps-package+xml"/>'
            "</rootfiles></container>",
        )
        epub.writestr("content.opf", opf)
        epub.writestr(
            "c1.xhtml",
            '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>c</title></head>'
            "<body><p>Chapter one.</p></body></html>",
        )
        epub.writestr(
            "toc.ncx",
            '<?xml version="1.0"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" '
            'version="2005-1"><head/><docTitle><text>t</text></docTitle><navMap/></ncx>',
        )
        epub.writestr("cover.png", ONE_PIXEL_PNG)


def run_image(*args, mount=None, entrypoint=None):
    command = ["docker", "run", *HARDENED]
    if mount:
        command += ["--mount", f"type=bind,src={mount},dst=/work"]
    if entrypoint:
        command += ["--entrypoint", entrypoint]
    return subprocess.run(
        [*command, IMAGE, *args], capture_output=True, text=True, timeout=300
    )


@pytest.fixture
def work(tmp_path):
    """A folder the container's user can write, whatever its UID."""
    for folder in (tmp_path / "tmp", tmp_path / "ingest"):
        folder.mkdir()
    for folder in (tmp_path, tmp_path / "tmp", tmp_path / "ingest"):
        folder.chmod(0o777)
    write_epub(tmp_path / "in.epub")
    # ebook-meta rewrites the book in place, so the file needs opening too.
    (tmp_path / "in.epub").chmod(0o666)
    return tmp_path


FEED_ONE_BOOK = """
import json, sys
from pathlib import Path
from feeder import Metadata, feed_book

metadata = Metadata(**json.loads(sys.argv[1]))
work = Path("/work")
print(json.dumps(feed_book(work / "in.epub", metadata, work / "tmp", work / "ingest")))
"""


class TestTheImage:
    def test_when_started_with_no_settings_runs_the_feeder_and_names_what_is_missing(
        self,
    ):
        result = run_image()

        assert result.returncode != 0
        assert "CHAPTARR_URL" in result.stderr

    def test_runs_as_a_user_other_than_root(self):
        result = run_image("-u", entrypoint="id")

        assert result.returncode == 0
        assert result.stdout.strip() != "0"

    def test_when_feeding_a_book_hands_it_to_cwa_with_metadata_calibre_reads_back(
        self, work
    ):
        result = run_image(
            "-c", FEED_ONE_BOOK, json.dumps(METADATA), mount=work, entrypoint="python3"
        )

        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == []
        assert (work / "ingest" / "hc-175780.epub").exists()

    def test_when_writing_metadata_calibre_reports_no_hidden_error(self, work):
        # ebook-meta exits 0 even when a library it needs is missing: the
        # error only shows as a traceback.
        result = run_image(
            "/work/in.epub",
            "--title",
            "Catching Fire",
            mount=work,
            entrypoint="ebook-meta",
        )

        assert result.returncode == 0, result.stderr
        assert "Traceback" not in result.stdout + result.stderr
