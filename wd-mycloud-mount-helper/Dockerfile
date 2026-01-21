ARG BUILD_FROM
FROM ${BUILD_FROM}

RUN apk add --no-cache python3 py3-pip
RUN pip3 install --no-cache-dir flask requests

COPY app /app
WORKDIR /app
CMD ["python3", "app.py"]
