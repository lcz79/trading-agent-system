FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY confluence.py .
COPY hl_market_data.py .

CMD ["python", "main.py"]
