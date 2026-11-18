FROM docker:27-cli

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apk add --no-cache python3 py3-pip
WORKDIR /app
COPY backend/requirements.txt /tmp/backend-requirements.txt
RUN pip install --break-system-packages --disable-pip-version-check -r /tmp/backend-requirements.txt

COPY backend ./backend
COPY worker ./worker
COPY orchestrator.py netlab.py pyproject.toml ./

EXPOSE 9000
CMD ["python3", "-m", "uvicorn", "worker.main:app", "--host", "0.0.0.0", "--port", "9000"]
