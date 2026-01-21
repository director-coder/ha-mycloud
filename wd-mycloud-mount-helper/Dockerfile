ARG BUILD_FROM
FROM ${BUILD_FROM}

# В python-базе уже есть python, но зависимости всё равно ставим
RUN apk add --no-cache py3-flask py3-requests

COPY app /app
WORKDIR /app

CMD ["python3", "/app/app.py"]
