# Usa un'immagine Python completa
FROM python:3.10

# Imposta la cartella di lavoro
WORKDIR /app

# Aggiorna pip, lo strumento di installazione
RUN pip install --upgrade pip

# --- LA LISTA DELLA SPESA FINALE ---
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" pandas "numpy<2.0.0" flask ccxt pybit ta

# 2. Copia il file ZIP di pandas-ta che abbiamo messo a mano nella cartella
COPY pandas-ta.zip .

# 3. Installa pandas-ta dal file locale, aggirando ogni problema di rete
RUN pip install --no-cache-dir pandas-ta.zip

# --- TRUCCO ANTI-CACHE ---
# Copia il file main.py individualmente per forzare Docker a "vederlo"
COPY main.py .

# Copia il resto del codice dell'applicazione
COPY . .

EXPOSE 8000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--loop", "asyncio"]
