FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY src/ ./src/
COPY scripts/ ./scripts/

# Create data directory for SQLite + fallback JSON
RUN mkdir -p /app/data

# Expose API port
EXPOSE 8000

CMD ["python", "-m", "src.main"]
