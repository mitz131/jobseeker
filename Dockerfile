# jobseeker: crawler, labelling and web page in one process (jobseeker serve).
# Data (jobs.db, the swisstopo locality register) lives in /app/data, a volume:
# the default paths in config.toml point there.
# Stock Ubuntu with its own Python 3.14, pinned by digest so every build starts from the
# same image. Not python:3.14-slim (Debian): Workday's Cloudflare answered every request
# from that image with a bot challenge (HTTP 429, Cf-Mitigated: challenge), whatever the
# User-Agent, while the same requests from Ubuntu's Python went through (2026-11-18).
FROM ubuntu:26.04@sha256:d66b366dac61b575bee2aef07e9c26e8070096fbe84a3d4d3eb0da069b5d76db
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

WORKDIR /app
# Dependencies first, from the lock file: exact versions, checked against their hashes,
# wheels only (no package's build code runs). Rebuilt only when the lock file changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir --require-hashes --only-binary :all: -r requirements.txt
COPY jobseeker ./jobseeker
COPY frontend/src ./frontend/src
COPY config.toml places.toml labels.toml ./
# The package runs from /app (python -m jobseeker), next to frontend/src: no install step.
# chmod: files keep the host's permissions on COPY, which can be owner-only.
# uid 1000 is the image's own "ubuntu" user (the pod runs as uid 1000), minus its extra groups (sudo, adm, ...).
RUN chmod -R a+rX /app \
    && usermod -G "" ubuntu \
    && mkdir data && chown ubuntu data

USER ubuntu
EXPOSE 8090
CMD ["python", "-m", "jobseeker", "serve", "--host", "0.0.0.0"]
