FROM python:3.11-slim

WORKDIR /app

# Copy package files
COPY pyproject.toml README.md ./

# Copy source code (needed before install for editable mode)
COPY src/ ./src/

# Install package in editable mode
RUN pip install --no-cache-dir -e .

# Create non-root user
RUN useradd -m -u 1000 syncuser && \
    chown -R syncuser:syncuser /app

USER syncuser

ENTRYPOINT ["immich-favorite-sync"]
