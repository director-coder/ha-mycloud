ARG BUILD_FROM
FROM ${BUILD_FROM}

# Всё через apk, без pip
RUN apk add --no-cache \
    python3 \
    py3-flask \
    py3-requests

COPY app /app
WORKDIR /app
CMD ["python3", "app.py"]
