FROM python:3.10-slim

WORKDIR /app

# Build dependencies for ccxt/pandas/numpy
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt .

# Install dependencies (including ccxt, pandas, numpy)
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Start the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
