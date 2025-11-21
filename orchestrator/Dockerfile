FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default to multi-user orchestrator
CMD ["python", "-u", "main_multiuser.py"]
