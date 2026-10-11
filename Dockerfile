# jobseeker: crawler, labelling and web page in one process (jobseeker serve).
# Data (jobs.db, the swisstopo locality register) lives in /app/data, a volume:
# the default paths in config.toml point there.
FROM python:3.14-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY jobseeker ./jobseeker
COPY frontend/src ./frontend/src
COPY config.toml places.toml labels.toml ./
# Editable, so the package stays in /app and finds frontend/src next to it.
# chmod: files keep the host's permissions on COPY, which can be owner-only.
RUN pip install --no-cache-dir -e . \
    && chmod -R a+rX /app \
    && useradd --uid 1000 --create-home jobseeker \
    && mkdir data && chown jobseeker data

USER jobseeker
EXPOSE 8090
CMD ["jobseeker", "serve", "--host", "0.0.0.0"]
