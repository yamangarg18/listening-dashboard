FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py .
COPY logger.py .
COPY main.py .
COPY setup_notion.py .
COPY notion_client.py .
COPY parallel_client.py .
COPY openai_client.py .
COPY ingestion.py .
COPY reconciliation.py .
COPY curation.py .
COPY escalation.py .
COPY dedup.py .
COPY scheduler.py .
COPY extract.py .
COPY health.py .

RUN mkdir -p /app/logs

CMD ["python", "main.py", "start"]
