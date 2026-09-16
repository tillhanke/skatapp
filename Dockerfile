FROM python:3.12-slim

WORKDIR /app

# System dependencies (if sqlite3 CLI is ever needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
 && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy only necessary application files
COPY app.py /app/
COPY db_setup.py /app/
COPY skat_engine.py /app/
COPY tisch.py /app/
COPY verlauf.py /app/
COPY index.html /app/
COPY script.js /app/
COPY style.css /app/
COPY suche.html /app/
COPY suche.js /app/
COPY spielen.html /app/
COPY spielen.js /app/

# Environment
ENV FLASK_APP=app.py \
    PYTHONUNBUFFERED=1 \
    SKAT_DB=/app/data/skat_daten.db

EXPOSE 5000

# gevent-Worker: nötig für Server-Sent-Events (langlebige Verbindungen).
# Bewusst genau EIN Worker: der Zustand laufender Remote-Tische liegt im
# Prozessspeicher und darf nicht über mehrere Worker verteilt werden.
CMD ["gunicorn", "-k", "gevent", "-w", "1", "-b", "0.0.0.0:5000", "--timeout", "0", "app:app"]
