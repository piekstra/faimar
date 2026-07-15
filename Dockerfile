FROM python:3.12-slim

WORKDIR /srv/faimar

COPY pyproject.toml README.md ./
COPY app ./app
COPY static ./static

RUN pip install --no-cache-dir .

# Put the cache on a mountable path so it survives restarts when hosted.
ENV FAIMAR_CACHE_PATH=/data/cache.db
RUN mkdir -p /data
VOLUME /data

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
