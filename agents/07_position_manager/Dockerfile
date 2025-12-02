FROM python:3.10-slim

WORKDIR /app

# Copia il file dei requisiti
COPY requirements.txt .

# Installa le dipendenze (incluso ccxt, pandas, numpy)
RUN pip install --no-cache-dir -r requirements.txt

# Copia il resto del codice
COPY . .

# Avvia l'applicazione
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
