FROM python:3.14-slim

# Python 3.14 note: If gunicorn compatibility issues arise,
# fall back to python:3.13-slim until gunicorn officially supports 3.14.

WORKDIR /app

# Install system dependencies for MariaDB client.
# tzdata is a defensive pin: python:3.14-slim already ships it, but pinning
# guards against future base-image variants dropping the package, which would
# break the static status page's local-timezone generation timestamp.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libzbar0 \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create uploads directory
RUN mkdir -p /app/uploads

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "2", "--access-logfile", "-", "esb:create_app()"]
