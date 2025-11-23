# Usa l'immagine Python slim come base
FROM python:3.9-slim

# Aggiorna l'elenco dei pacchetti e installa curl
RUN apt-get update && apt-get install -y curl

# Imposta la directory di lavoro all'interno del container
WORKDIR /app

# Copia il file delle dipendenze e installale
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia il resto del codice dell'applicazione
COPY . .

# Comando per avviare il server quando il container parte
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
