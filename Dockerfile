FROM python:3.11-slim

# System deps for PDF→SVG/PNG and fonts
RUN apt-get update && apt-get install -y --no-install-recommends     poppler-utils ca-certificates fonts-lmodern &&     rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY . .

# Use bundled tectonic if present at bin/tectonic
ENV PATH="/app/bin:${PATH}"
ENV DJANGO_SETTINGS_MODULE=app.settings
ENV PYTHONUNBUFFERED=1

# If you serve static via WhiteNoise, you can pre-collect:
# RUN python manage.py collectstatic --noinput

# Render provides $PORT
CMD gunicorn app.wsgi:application --workers 3 --timeout 90 --bind 0.0.0.0:$PORT --log-file -
