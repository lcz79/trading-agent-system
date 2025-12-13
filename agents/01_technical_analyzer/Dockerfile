FROM python:3.10-slim

WORKDIR /app

# Install build dependencies for scientific stack (prophet, matplotlib, numpy, etc.)
RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    g++ \
    make \
    gfortran \
    libopenblas-dev \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY indicators.py .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
