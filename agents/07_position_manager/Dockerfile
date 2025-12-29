FROM python:3.10-slim

WORKDIR /app

# Force IPv4 for apt (fixes exit code 100 on some hosts with flaky IPv6)
RUN printf 'Acquire::ForceIPv4 "true";\n' > /etc/apt/apt.conf.d/99force-ipv4

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
