FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY backend/requirements.txt /tmp/backend-requirements.txt
RUN pip install --disable-pip-version-check -r /tmp/backend-requirements.txt

COPY backend ./backend
COPY orchestrator.py netlab.py topology.json pyproject.toml ./
RUN mkdir -p /data/netlab

EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
