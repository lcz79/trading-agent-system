# Usa un'immagine Python ufficiale come base
FROM python:3.9-slim

# Imposta la directory di lavoro all'interno del container
WORKDIR /app

# Copia i file dei requisiti e installa le dipendenze
COPY requirements.txt .
RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi

# Installa solo le dipendenze necessarie
RUN pip install fastapi uvicorn

# Copia il codice dell'applicazione nella directory di lavoro
COPY . .

# Esponi la porta su cui l'applicazione girerà
EXPOSE 8000

# Comando per avviare l'applicazione quando il container parte
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
