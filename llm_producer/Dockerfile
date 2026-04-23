FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY producer.py .

ENV SIGNAL_FILE=/freqtrade/user_data/llm_signals.json
ENV INTERVAL_SECONDS=3600

CMD ["python3", "-u", "producer.py"]
