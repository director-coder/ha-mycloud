ARG BUILD_FROM
FROM ${BUILD_FROM}

# venv + pip внутри venv (обходит PEP668 и не зависит от apk-python paths)
RUN python3 -m venv /opt/venv \
  && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
  && /opt/venv/bin/pip install --no-cache-dir flask requests

COPY app /app
WORKDIR /app

CMD ["/usr/bin/with-contenv", "/opt/venv/bin/python", "/app/app.py"]
