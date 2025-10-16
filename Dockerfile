FROM python:3.9-slim-buster
LABEL Maintainer="astronaut@footprintsonthemoon.ch"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

EXPOSE 5000
# Hinweis: timeout 0 = unendlich; fuer Prod meist 60-120 sinnvoll
CMD ["gunicorn", "--workers", "2", "--timeout", "120", "--bind", "0.0.0.0:5000", "app:app"]
