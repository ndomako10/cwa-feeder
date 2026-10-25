"""A stand-in for Calibre's ebook-meta, shared by the feeder's tests."""

from xml.sax.saxutils import escape, quoteattr

import pytest

OPF = """<?xml version='1.0' encoding='utf-8'?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"
      xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:title>{title}</dc:title>
    <dc:creator opf:role="aut">{authors}</dc:creator>
    <dc:description>{comments}</dc:description>
    <dc:identifier opf:scheme="HARDCOVER-ID">{hardcover_id}</dc:identifier>
    <meta name="calibre:series" content={series}/>
    <meta name="calibre:series_index" content={index}/>
  </metadata>
</package>
"""


class FakeEbookMeta:
    """Writes and reads metadata the way ebook-meta does, without Calibre.

    ``misread`` swaps fields in what is read back, as a faulty write would.
    """

    def __init__(self, has_cover=True, misread=None):
        self.has_cover = has_cover
        self.misread = misread or {}
        self.calls = []
        self.written = {}

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        options = args[2:]
        if "--to-opf" in options:
            self._write_opf(options[options.index("--to-opf") + 1])
        elif options and options[0].startswith("--get-cover="):
            if self.has_cover:
                with open(options[0].removeprefix("--get-cover="), "wb") as f:
                    f.write(b"jpeg")
        else:
            self.written = dict(zip(options[::2], options[1::2], strict=True))

    def _write_opf(self, path):
        fields = {
            "title": self.written.get("--title", ""),
            "authors": self.written.get("--authors", ""),
            "comments": self.written.get("--comments", ""),
            "hardcover_id": self.written.get("--identifier", "").removeprefix(
                "hardcover-id:"
            ),
            "series": self.written.get("--series", ""),
            "index": self.written.get("--index", "1"),
        }
        fields.update(self.misread)
        with open(path, "w", encoding="utf-8") as f:
            f.write(
                OPF.format(
                    title=escape(fields["title"]),
                    authors=escape(fields["authors"]),
                    comments=escape(fields["comments"]),
                    hardcover_id=escape(fields["hardcover_id"]),
                    series=quoteattr(fields["series"]),
                    index=quoteattr(fields["index"]),
                )
            )


@pytest.fixture
def fake_ebook_meta():
    return FakeEbookMeta
