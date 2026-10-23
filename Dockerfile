FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY main.py auth.py ./
COPY core/ ./core/
COPY bot/ ./bot/
COPY userbot/ ./userbot/
COPY img/ ./img/
COPY scripts/ ./scripts/

CMD ["python", "main.py"]
