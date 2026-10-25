"""How the feeder writes metadata into an EPUB and checks it.

The OPF below is the shape Calibre 9.1's `ebook-meta --to-opf` gave for
Catching Fire in CWA's library (2026-10-20).
"""

from feeder import EBOOK_META, Metadata, ebook_meta_args, verify_opf

METADATA = Metadata(
    title="Catching Fire",
    author="Suzanne Collins",
    hardcover_id="175780",
    series="The Hunger Games",
    series_index="2",
    description="Katniss has won the Hunger Games.",
    date="2009-09-01",
    tags=["Dystopian", "Young Adult"],
    isbn="9781407133188",
    publisher="Scholastic",
)

OPF = """<?xml version='1.0' encoding='utf-8'?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="calibre_id"
    version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"
      xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:title>Catching Fire</dc:title>
    <dc:creator opf:role="aut" opf:file-as="Collins, Suzanne">{author}</dc:creator>
    <dc:identifier id="calibre_id" opf:scheme="calibre">ebb61b89</dc:identifier>
    <dc:date>2009-09-01T00:00:00+00:00</dc:date>
    <dc:description>{description}</dc:description>
    <dc:identifier opf:scheme="HARDCOVER-ID">175780</dc:identifier>
    <dc:subject>Dystopian</dc:subject>
    <meta name="calibre:series" content="The Hunger Games"/>
    <meta name="calibre:series_index" content="{series_index}"/>
  </metadata>
</package>
"""


def opf(author="Suzanne Collins", description="Katniss won.", series_index="2"):
    return OPF.format(author=author, description=description, series_index=series_index)


class TestEbookMetaArgs:
    def test_given_complete_metadata_writes_every_field(self):
        assert ebook_meta_args("/work/hc-175780.epub", METADATA) == [
            EBOOK_META,
            "/work/hc-175780.epub",
            "--title",
            "Catching Fire",
            "--authors",
            "Suzanne Collins",
            "--identifier",
            "hardcover-id:175780",
            "--series",
            "The Hunger Games",
            "--index",
            "2",
            "--comments",
            "Katniss has won the Hunger Games.",
            "--date",
            "2009-09-01",
            "--tags",
            "Dystopian,Young Adult",
            "--isbn",
            "9781407133188",
            "--publisher",
            "Scholastic",
        ]

    def test_given_missing_fields_leaves_the_files_own_values_alone(self):
        sparse = Metadata(
            title="Catching Fire",
            author="Suzanne Collins",
            hardcover_id="175780",
            series=None,
            series_index=None,
            description="Katniss has won the Hunger Games.",
            date=None,
            tags=[],
            isbn=None,
            publisher=None,
        )

        args = ebook_meta_args("/work/hc-175780.epub", sparse)

        for option in ("--series", "--index", "--date", "--tags", "--isbn"):
            assert option not in args

    def test_given_a_tag_with_a_comma_keeps_it_one_tag(self):
        metadata = Metadata(**{**vars(METADATA), "tags": ["Science Fiction, Hard"]})

        args = ebook_meta_args("/work/hc-175780.epub", metadata)

        assert args[args.index("--tags") + 1] == "Science Fiction; Hard"


class TestVerifyOpf:
    def test_given_the_file_holds_what_was_written_reports_no_mismatches(self):
        assert verify_opf(opf(), METADATA) == []

    def test_given_calibre_wrote_the_index_as_a_decimal_still_matches(self):
        assert verify_opf(opf(series_index="2.0"), METADATA) == []

    def test_given_a_different_author_reports_the_author(self):
        assert verify_opf(opf(author="Someone Else"), METADATA) == ["author"]

    def test_given_an_empty_description_reports_the_description(self):
        assert verify_opf(opf(description=""), METADATA) == ["description"]

    def test_given_a_different_series_index_reports_it(self):
        assert verify_opf(opf(series_index="3"), METADATA) == ["series_index"]

    def test_given_no_series_to_write_accepts_whatever_series_the_file_has(self):
        metadata = Metadata(**{**vars(METADATA), "series": None, "series_index": None})

        assert verify_opf(opf(), metadata) == []
