FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /workspace_repo

COPY requirements /tmp/requirements
RUN pip install --upgrade pip && pip install -r /tmp/requirements/api.txt

COPY . /workspace_repo

ENV PYTHONPATH=/workspace_repo:/workspace_repo/apps/api
WORKDIR /workspace_repo/apps/api

CMD ["sh", "-c", "python /workspace_repo/scripts/run_migrations.py && uvicorn main:app --host 0.0.0.0 --port 8000"]
