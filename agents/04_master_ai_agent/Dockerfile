# Usa un'immagine Python ufficiale e leggera
FROM python:3.9-slim

# Imposta la cartella di lavoro dentro il container
WORKDIR /app

# Copia il file delle dipendenze e installale
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia il resto del codice dell'applicazione
COPY . .

# Comando per avviare l'applicazione quando il container parte
# L'agente sarà in ascolto sulla porta 8000 all'interno del container
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
