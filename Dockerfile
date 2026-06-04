# Container build for the geonlp mining workers.
# Mirrors the image used in production at paper submission.

FROM python:3.11-slim

WORKDIR /app

# System dependencies for psycopg2 source build and NLTK data download.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies first so layer caches well.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download NLTK corpora needed by services/mining/text_processing.py
# and services/mining/cooccurrence.py.
RUN python -m nltk.downloader -d /usr/share/nltk_data \
        wordnet \
        omw-1.4 \
        stopwords \
        punkt

ENV NLTK_DATA=/usr/share/nltk_data
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Source.
COPY services/ services/
COPY scripts/ scripts/
COPY db/ db/

# Default command runs the mining worker. CronJob manifests override this
# with --class flags to scope the worker to a specific pool.
CMD ["python", "scripts/process_pending_terms.py"]
