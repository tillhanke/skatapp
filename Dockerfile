FROM python:3.12-slim

WORKDIR /app

# System dependencies (if sqlite3 CLI is ever needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
 && rm -rf /var/lib/apt/lists/*

# Copy only necessary application files
COPY app.py /app/
COPY index.html /app/
COPY script.js /app/
COPY style.css /app/
COPY suche.html /app/
COPY suche.jl /app/

# Python dependencies
RUN pip install --no-cache-dir flask gunicorn

# Environment
ENV FLASK_APP=app.py \
    PYTHONUNBUFFERED=1

EXPOSE 5000

# Run the Flask app with gunicorn
CMD ["gunicorn", "-b", "0.0.0.0:5000", "app:app"]

