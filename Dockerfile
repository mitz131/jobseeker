# jobseeker: crawler, labelling and web page in one process (jobseeker serve).
# Data (jobs.db, the swisstopo locality register) lives in /app/data, a volume:
# the default paths in config.toml point there.
# Pinned by digest, so every build starts from the same image; Dependabot proposes updates.
FROM python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f

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
RUN chmod -R a+rX /app \
    && useradd --uid 1000 --create-home jobseeker \
    && mkdir data && chown jobseeker data

USER jobseeker
EXPOSE 8090
CMD ["python", "-m", "jobseeker", "serve", "--host", "0.0.0.0"]
