# The CWA feeder's image: Python, Calibre's command-line tools and
# feeder.py, nothing else. tests/test_image.py runs the built image with
# the restrictions the README recommends for running it.

# ---------------------------------------------------------------------------
# Stage 1: download Calibre and check it is the file its author published.
# Nothing from this stage reaches the final image except /opt/calibre, so
# xz-utils and the archive are left behind.
# ---------------------------------------------------------------------------
FROM python:3.13-slim@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f AS calibre

# renovate: datasource=github-releases depName=kovidgoyal/calibre
ARG CALIBRE_VERSION=9.1.0
# Published by Calibre at
# https://calibre-ebook.com/signatures/calibre-<version>-x86_64.txz.sha512
ARG CALIBRE_SHA512=3e5a58a6d95b533662fecebf1867edb848bf293b8062930e62fbaa631dec8a004e8e4b627dc268e94f409ee6df6c11dbe77815eb051a7178016200546c6f08ff

ADD https://download.calibre-ebook.com/${CALIBRE_VERSION}/calibre-${CALIBRE_VERSION}-x86_64.txz /tmp/calibre.txz

# Without pipefail, a RUN line's status is only its last command's.
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# sha512sum -c fails the build if the archive isn't byte-for-byte the one
# published, so a tampered or truncated download never becomes an image.
# Debian drops a package's old versions from its mirrors when a security
# update lands, so pinning apt versions would break the build; the base
# image's digest pins the release instead.
# The archive ships resources/locales as root-only (0700), which the
# non-root user in stage 2 couldn't read; a+rX opens it read-only.
# hadolint ignore=DL3008
RUN echo "${CALIBRE_SHA512}  /tmp/calibre.txz" | sha512sum -c - \
    && apt-get update \
    && apt-get install -y --no-install-recommends xz-utils \
    && mkdir /opt/calibre \
    && tar -xJf /tmp/calibre.txz -C /opt/calibre \
    && chmod -R a+rX /opt/calibre

# ---------------------------------------------------------------------------
# Stage 2: the image that runs.
# ---------------------------------------------------------------------------
FROM python:3.13-slim@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f

# The libraries Calibre's tools need on this base, found by trial. With
# only some of them, ebook-meta still exits 0 but can't re-encode the
# cover. Not version-pinned, for the reason in stage 1.
# feeder.py uses only the standard library, so pip goes: it would only
# be a way to install code at run time, and it vendors its own copies of
# urllib3 and certifi that the image scan flags.
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends \
        libegl1 \
        libfontconfig1 \
        libglx0 \
        libopengl0 \
        libxcb1 \
        libxkbcommon0 \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m pip uninstall --yes --no-cache-dir pip

COPY --from=calibre /opt/calibre /opt/calibre

# feeder.py calls plain `ebook-meta`. The container runs read-only with
# only /tmp writable, and Calibre keeps its settings under HOME.
ENV PATH="/opt/calibre:${PATH}" \
    HOME=/tmp \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Last, so a feeder change rebuilds and ships only this small layer.
WORKDIR /app
COPY feeder.py .

# Numeric, so Kubernetes-style runAsNonRoot checks can verify it without
# a passwd entry; no account is needed, since HOME is set above.
USER 10001:10001

ENTRYPOINT ["python3", "/app/feeder.py"]
