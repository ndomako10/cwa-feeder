# cwa-feeder

Copies the ebooks Chaptarr manages into [Calibre-Web Automated](https://github.com/crocodilestick/Calibre-Web-Automated)
(CWA), with complete metadata written into each file first: title,
author, series and number, description, published date, genre tags,
ISBN, publisher and Hardcover ID.

CWA's own metadata fetch searches by title and author and often picks
the wrong book. Chaptarr already knows each book's exact Hardcover ID
and series, so the feeder uses those, and looks up the rest from
[Hardcover](https://hardcover.app/) by ID.

## How it works

The feeder runs in a loop. Each pass reconciles the whole library
rather than reacting to imports, so a pass that fails part-way, or a
book imported while CWA was down, is picked up on the next one.

1. List every Chaptarr ebook with an EPUB file, keyed by Hardcover ID.
2. Read the Hardcover IDs already in CWA's `metadata.db` (read-only)
   and those waiting in its ingest folder.
3. For each book missing from both, copy its EPUB to a work folder,
   write the metadata with Calibre's `ebook-meta`, read it back, and
   move the file into CWA's ingest folder. The move is a rename on the
   same mount, so CWA never sees a partial file.
4. Rewrite a report of every book that was held, failed, skipped or is
   missing optional fields, with the reason.

The library's files are only ever read. The copy is what gets written,
so a file that is also seeding a torrent is left untouched.

### Metadata and its sources

| Field | Source | If missing |
|---|---|---|
| Title, author | Chaptarr's ebook record | Held |
| Hardcover ID | Chaptarr | Skipped: it can't be matched |
| Series and number | Chaptarr's series title, split at the last ` #` | Fed; reported only if Hardcover lists a series |
| Description | Hardcover | Held |
| Published date | Hardcover, else Chaptarr's release date | Fed, reported |
| Genre tags | Hardcover's top five | Fed, reported |
| ISBN, publisher | Chaptarr's monitored edition, else Hardcover | Fed, reported |
| Cover | The EPUB's own | Fed, reported |

A held book stays out of CWA and is retried on every pass, so CWA never
receives a book missing a required field.

Turn off CWA's "Enable Auto-Metadata Fetch": in its default mode it
replaces the feeder's metadata with a search match.

## Running it

The image is `ghcr.io/ndomako10/cwa-feeder`. Pin it by version and
digest; there is no `latest` tag.

```yaml
services:
  cwa-feeder:
    image: ghcr.io/ndomako10/cwa-feeder:0.1.0@sha256:<digest>
    restart: unless-stopped
    user: "1000:1000"
    read_only: true
    tmpfs:
      - /tmp
    cap_drop: [ALL]
    security_opt:
      - no-new-privileges:true
    environment:
      CHAPTARR_URL: http://chaptarr:8789
      CHAPTARR_API_KEY: ${CHAPTARR_API_KEY}
      HARDCOVER_TOKEN: ${HARDCOVER_TOKEN}
    volumes:
      - /path/to/cwa-data:/calibre
      - /path/to/cwa-data/library:/calibre/library:ro
      - /data/media/books/ebooks:/data/media/books/ebooks:ro
```

- **`/calibre`** holds CWA's `library/` and `ingest/` folders. The
  feeder writes `feeder/work/`, `feeder/report.json` and files in
  `ingest/`. The work folder and ingest folder must be on the same
  mount, so the hand-over is a rename.
- **`/calibre/library`** is mounted again read-only, so the feeder can
  read CWA's database but never write the library.
- **The ebook folder** is mounted read-only at the same path Chaptarr
  uses, so the paths in Chaptarr's API resolve as they are.
- **`user`** should own files the way CWA expects in its ingest folder.
  The image's default user is `10001`.

### Settings

| Variable | Required | Meaning |
|---|---|---|
| `CHAPTARR_URL` | Yes | Chaptarr's base URL |
| `CHAPTARR_API_KEY` | Yes | Chaptarr's API key; the feeder only reads with it |
| `HARDCOVER_TOKEN` | Yes | A Hardcover API token. A leading `Bearer ` is stripped |
| `FEED_INTERVAL_SECONDS` | No | The wait between passes, 300 by default |

The feeder exits naming any required variable that is missing. It logs
one JSON line per event on stdout.

## The image

- `python:3.13-slim`, pinned by digest.
- Calibre's official Linux build in `/opt/calibre`, checked against the
  SHA-512 Calibre publishes for it.
- The six libraries Calibre's command-line tools need to load. With
  only some of them, `ebook-meta` exits 0 but silently fails to
  re-encode the cover.
- `feeder.py`, which uses only the Python standard library. pip is
  removed.

It is about 1.4 GB, almost all Calibre. `feeder.py` is the last layer,
so a feeder-only release downloads a few kilobytes.

## Development

```sh
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt   # .venv/Scripts/ on Windows
.venv/bin/pre-commit install
.venv/bin/pytest
```

The unit tests mock Chaptarr, Hardcover and `ebook-meta`. The image
tests run the built image, with the restrictions above, against a real
EPUB and the real Calibre:

```sh
docker build -t cwa-feeder:dev .
CWA_FEEDER_IMAGE=cwa-feeder:dev .venv/bin/pytest tests/test_image.py
```

CI runs the pre-commit hooks, hadolint, both test suites and a Trivy
scan that fails on any HIGH or CRITICAL finding with a fix available.

### Releases

Versions follow [Semantic Versioning](https://semver.org/). To release,
update `CHANGELOG.md` with [git-cliff](https://git-cliff.org/), commit,
and push a `vX.Y.Z` tag. CI builds, tests and scans the image again,
pushes it, and prints the `version@digest` pin in the run summary. It
refuses a version that already exists.

A Calibre update from Renovate fails the build until `CALIBRE_SHA512`
in the Dockerfile is updated from
`https://calibre-ebook.com/signatures/calibre-<version>-x86_64.txz.sha512`.
Keep Calibre's major version in step with the one CWA ships.

## Licence

[GPL-3.0](LICENSE). The image includes Calibre, which is also GPL-3.0;
its source for each release is at
[download.calibre-ebook.com](https://download.calibre-ebook.com/), and
the version in an image is the `CALIBRE_VERSION` in its Dockerfile.
