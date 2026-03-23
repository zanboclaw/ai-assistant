FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /workspace_repo

COPY requirements /tmp/requirements
RUN pip install --upgrade pip && pip install -r /tmp/requirements/scheduler.txt

COPY . /workspace_repo

ENV PYTHONPATH=/workspace_repo

CMD ["python", "/workspace_repo/scripts/daily_review_scheduler.py"]
