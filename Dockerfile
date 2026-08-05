# ─── Base Image ───────────────────────────────────────────────────────────────
# Uses Debian Bookworm, which Playwright officially and natively supports.
FROM python:3.11-bookworm

# ─── Environment Variables ────────────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Set the internal working directory
WORKDIR /app

# ─── System Dependencies ──────────────────────────────────────────────────────
# Install build tools + OpenCL ICD loader (for Intel GPU via OpenVINO)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    cargo \
    rustc \
    tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# ─── Python & Pip Dependencies ────────────────────────────────────────────────
COPY requirements.txt .

# Upgrade pip and install all Python packages listed in requirements.txt
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# ─── Playwright & NLP Pre-downloads ──────────────────────────────────────────
RUN playwright install chromium --with-deps

# Pre-download the standard spaCy English model so it's ready for your NLP code
RUN python -m spacy download en_core_web_sm

# ─── Application Source ──────────────────────────────────────────────────────
COPY . .

# ─── Default Entrypoint ──────────────────────────────────────────────────────
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
