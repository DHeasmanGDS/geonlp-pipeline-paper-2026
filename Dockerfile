# Use a minimal Python base image
FROM python:3.11-slim

# Environment setup
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# System dependencies (for psycopg2, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Pre-download NLTK corpora used by the mining worker. Done at build time
# so the running container has no internet dependency for tokenization.
RUN python -c "import nltk; nltk.download('stopwords', quiet=True); nltk.download('wordnet', quiet=True); nltk.download('punkt', quiet=True); nltk.download('punkt_tab', quiet=True)"

# Copy the entire project
COPY . .

# Expose FastAPI default port
EXPOSE 8000

# Entry point for Uvicorn (production-ready)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
