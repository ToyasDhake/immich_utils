FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    IMMICH_UTILS_OUTPUT=/downloads

WORKDIR /app

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /downloads \
    && chown appuser:appuser /downloads

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./

VOLUME /downloads

USER appuser

CMD ["sh"]
