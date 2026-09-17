FROM python:3.12-slim

WORKDIR /srv

RUN useradd --create-home --uid 10001 appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

ENV PYTHONUNBUFFERED=1 \
    PORT=8080 \
    F1_SEASON=current \
    F1_CACHE_TTL=300

EXPOSE 8080

USER appuser

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
