# 🚀 CORSO COMPLETO: COME HO CREATO IL MIO TRADING BOT CON AI

## 📋 PROMPT PER GAMMA.APP

---

# MODULO 0: INTRODUZIONE AL CORSO

## Slide 1: Copertina
**Titolo:** MITRAGLIERE - IL MIO TRADING BOT AUTOMATICO CON AI
**Sottotitolo:** Da Zero a Trader Automatico: Come Ho Creato un Sistema Multi-Agente per il Trading di Criptovalute
**Stile visivo:** Background scuro con effetti neon verdi e blu, icone crypto (Bitcoin, Ethereum), circuiti digitali, effetto glow
**Note:** Logo centrale con il nome "MITRAGLIERE" in font futuristico Orbitron

## Slide 2: Chi Sono e Perché Questo Corso
**Contenuto:**
- Non sono un programmatore professionista
- Non ero un trader esperto
- Ho usato l'AI come mio co-pilota
- In questo corso imparerai il MIO METODO: far "competere" diversi LLM per ottenere codice migliore
- Ogni passo sarà guidato e replicabile
**Stile visivo:** Foto placeholder persona + icone AI (ChatGPT, Claude, Gemini)

## Slide 3: Cosa Costruiremo
**Contenuto:**
- Un sistema COMPLETO di trading automatico
- 9 agenti specializzati che lavorano insieme
- Dashboard in tempo reale per monitorare tutto
- Connessione reale a Bybit per trading crypto
**Elementi visivi:** Schema architettura con 9 blocchi colorati connessi
**Colori:** Neon verde (#00ff9d), Blu cyber (#00f3ff), Rosso alert (#ff2a6d)

## Slide 4: Struttura del Corso
**Contenuto:**
| Modulo | Argomento |
|--------|-----------|
| 1 | Introduzione all'Intelligenza Artificiale |
| 2 | Il Mondo delle Criptovalute e Trading |
| 3 | L'Ambiente di Sviluppo (Python, VS Code, GitHub) |
| 4 | Docker e Deploy su Server |
| 5 | I Nostri 9 Agenti AI |
| 6 | Configurazione e Test |
| 7 | Dashboard di Monitoraggio |
| 8 | Strategie Avanzate e Ottimizzazione |

---

# MODULO 1: INTRODUZIONE ALL'INTELLIGENZA ARTIFICIALE

## Slide 1.1: Cos'è l'Intelligenza Artificiale?
**Contenuto:**
- L'AI è un programma che impara dai dati
- I Large Language Models (LLM) sono AI che "parlano" con noi
- ChatGPT, Claude, Gemini, Copilot sono LLM
- NON devi capire come funzionano internamente
- Devi solo sapere come CHIEDERE le cose giuste
**Stile visivo:** Cervello stilizzato con circuiti, neon blu

## Slide 1.2: Gli LLM Che Useremo
**Contenuto:**
- **ChatGPT (OpenAI):** Il più popolare, ottimo per coding
- **Claude (Anthropic):** Eccellente per ragionamento lungo
- **Gemini (Google):** Buono per ricerche e verifica
- **GitHub Copilot:** Integrato direttamente nel codice
**Suggerimento:** Testa tutti! Ognuno ha punti di forza diversi
**Stile visivo:** 4 card con logo di ogni AI

## Slide 1.3: IL MIO METODO - La Competizione tra LLM ⭐
**Contenuto FONDAMENTALE:**
```
1. Chiedo a ChatGPT di scrivere un codice
2. Copio il codice e lo incollo in Claude
3. Chiedo: "Questo codice è corretto? Può essere migliorato?"
4. Se Claude suggerisce modifiche, le applico
5. Ripeto con Gemini per tripla verifica
6. Il risultato finale è MIGLIORE di quello che ogni singola AI avrebbe prodotto
```
**Stile visivo:** Diagramma ciclico con le 3 AI che si passano il codice

## Slide 1.4: Come Fare Domande Efficaci all'AI
**Contenuto:**
### Domanda SBAGLIATA:
"Fammi un bot di trading"

### Domanda GIUSTA:
"Voglio creare un agente Python con FastAPI che:
- Riceve un simbolo crypto (es. BTCUSDT)
- Scarica le ultime 200 candele da Bybit
- Calcola RSI a 14 periodi
- Calcola le medie mobili EMA 20 e 50
- Ritorna un JSON con trend, RSI e supporti/resistenze"

**Regola d'oro:** Più sei specifico, migliore sarà il risultato

## Slide 1.5: Prompt Engineering per Principianti
**Contenuto:**
### Struttura del Prompt Perfetto:
1. **CONTESTO:** "Sono un principiante che sta costruendo..."
2. **OBIETTIVO:** "Voglio che questo codice faccia..."
3. **DETTAGLI TECNICI:** "Usa Python 3.10, FastAPI, la libreria ta..."
4. **OUTPUT DESIDERATO:** "Restituisci un JSON con questi campi..."
5. **VINCOLI:** "Il codice deve essere commentato in italiano"

**Stile visivo:** Puzzle che si compone

## Slide 1.6: GPT-5.1 - L'AI del Nostro Bot
**Contenuto:**
Il nostro sistema usa **GPT-5.1** (o versione più recente disponibile) per le decisioni di trading.
Perché?
- Capacità di ragionamento avanzato
- Risposta in formato JSON strutturato
- Può analizzare dati di mercato complessi
- È stato addestrato per essere "decisivo" non solo "consigliante"
**Stile visivo:** Icona OpenAI con effetto glow verde

---

# MODULO 2: IL MONDO DELLE CRIPTOVALUTE E DEL TRADING

## Slide 2.1: Cosa Sono le Criptovalute?
**Contenuto:**
- Monete digitali decentralizzate
- Bitcoin (BTC) - La prima e più famosa
- Ethereum (ETH) - Smart contracts
- Solana (SOL) - Veloce e economica
- USDT - Stablecoin ancorata al dollaro
**Stile visivo:** Loghi crypto con effetto neon dorato

## Slide 2.2: Cos'è il Trading di Crypto?
**Contenuto:**
- Comprare a prezzo basso, vendere a prezzo alto (LONG)
- Vendere a prezzo alto, comprare a prezzo basso (SHORT)
- Il mercato crypto è APERTO 24/7/365
- Volatilità = Opportunità (ma anche rischio!)
**Stile visivo:** Grafico candlestick verde/rosso

## Slide 2.3: Bybit - Il Nostro Exchange
**Contenuto:**
- Piattaforma professionale per trading crypto
- Futures Perpetual (USDT) = Puoi usare leva
- API disponibili per trading automatico
- **TESTNET gratuito** per testare senza rischiare soldi veri
**Screenshot:** Homepage Bybit con frecce che indicano sezioni importanti

## Slide 2.4: Cos'è la Leva (Leverage)?
**Contenuto:**
| Leva | Investo | Controllo | Guadagno/Perdita x |
|------|---------|-----------|-------------------|
| 1x   | $100    | $100      | 1x                |
| 5x   | $100    | $500      | 5x                |
| 10x  | $100    | $1000     | 10x               |

⚠️ **ATTENZIONE:** La leva amplifica sia guadagni che perdite!
**Stile visivo:** Bilancia con pesi che si muovono

## Slide 2.5: Concetti Base del Trading
**Contenuto:**
- **LONG:** Scommetto che il prezzo SALIRÀ
- **SHORT:** Scommetto che il prezzo SCENDERÀ
- **Stop Loss (SL):** Chiudo la posizione se perdo troppo
- **Take Profit (TP):** Chiudo la posizione quando guadagno abbastanza
- **Entry Price:** Prezzo a cui apro la posizione
- **PnL:** Profitti e Perdite (Profit and Loss)
**Stile visivo:** Frecce verdi su/rosse giù

## Slide 2.6: Indicatori Tecnici Che Useremo
**Contenuto:**
- **RSI (Relative Strength Index):** Se < 30 = Ipervenduto (comprare?), Se > 70 = Ipercomprato (vendere?)
- **EMA (Exponential Moving Average):** Media mobile che segue il trend
- **MACD:** Incrocio di medie per confermare il trend
- **ATR (Average True Range):** Volatilità del mercato
- **Fibonacci:** Livelli di supporto/resistenza basati su rapporti matematici
- **Gann:** Cicli temporali e geometrici
**Stile visivo:** Mini grafici con indicatori sovrapposti

## Slide 2.7: Fear & Greed Index
**Contenuto:**
- Misura il SENTIMENTO del mercato
- 0-25: Extreme Fear (Paura estrema) - Potenziale occasione di acquisto → Considera posizioni LONG
- 25-50: Fear - Mercato nervoso → Monitora, aspetta conferme tecniche
- 50-75: Greed - Mercato ottimista → Trend rialzista, attenzione ai livelli di resistenza
- 75-100: Extreme Greed - Potenziale inversione → Considera Take Profit o evita nuovi LONG
**Stile visivo:** Termometro colorato dal verde al rosso

---

# MODULO 3: L'AMBIENTE DI SVILUPPO

## Slide 3.1: Gli Strumenti Necessari
**Contenuto:**
| Tool | Scopo | Costo |
|------|-------|-------|
| Python 3.10+ | Linguaggio di programmazione | Gratis |
| VS Code | Editor di codice | Gratis |
| GitHub | Versionamento e backup codice | Gratis |
| Docker | Containerizzazione | Gratis |
| GitHub Copilot | AI che scrive codice | $10/mese |
| OpenAI API | Cervello del bot | Pay-per-use |
| VPS Server | Dove gira il bot 24/7 | $5-20/mese |

## Slide 3.2: Installare Python
**Contenuto:**
1. Vai su python.org/downloads
2. Scarica Python 3.10 o superiore
3. Durante l'installazione, spunta "Add Python to PATH"
4. Verifica con terminale: `python --version`

**Screenshot:** Pagina download Python + installer con PATH evidenziato

## Slide 3.3: Installare VS Code
**Contenuto:**
1. Vai su code.visualstudio.com
2. Scarica per il tuo sistema operativo
3. Installa le estensioni:
   - Python (Microsoft)
   - Pylance
   - GitHub Copilot
   - Docker
**Screenshot:** VS Code con estensioni installate

## Slide 3.4: Configurare GitHub Copilot
**Contenuto:**
1. Abbonati su github.com/features/copilot
2. Installa l'estensione in VS Code
3. Fai login con il tuo account GitHub
4. Ora mentre scrivi, Copilot suggerirà il codice!

**Trucco:** Scrivi un commento che descrive cosa vuoi, Copilot completerà il codice
```python
# Funzione che calcola RSI con periodo 14
def calculate_rsi(data, period=14):
    # Copilot completerà automaticamente!
```

## Slide 3.5: Git e GitHub per Principianti
**Contenuto:**
Git = Sistema per salvare "versioni" del tuo codice
GitHub = "Cloud" dove salvare il tuo progetto

### Comandi base:
```bash
git init                    # Inizializza repository
git add .                   # Aggiungi tutti i file
git commit -m "messaggio"   # Salva una versione
git push                    # Carica su GitHub
git pull                    # Scarica da GitHub
```

## Slide 3.6: Creare il Tuo Repository
**Contenuto:**
1. Vai su github.com e fai login
2. Clicca "New repository"
3. Nome: `trading-agent-system`
4. Descrizione: "Bot di trading multi-agente con AI"
5. Seleziona "Private" (per sicurezza)
6. Clicca "Create"

**Screenshot:** Form creazione repo con campi compilati

## Slide 3.7: La Struttura del Nostro Progetto
**Contenuto:**
```
trading-agent-system/
├── agents/
│   ├── 01_technical_analyzer/
│   ├── 03_fibonacci_agent/
│   ├── 04_master_ai_agent/
│   ├── 05_gann_analyzer_agent/
│   ├── 06_news_sentiment_agent/
│   ├── 07_position_manager/
│   ├── 08_forecaster_agent/
│   ├── 09_whale_alert_agent/
│   └── orchestrator/
├── dashboard/
├── docker-compose.yml
├── .env
└── README.md
```
**Stile visivo:** Albero di cartelle con icone colorate

---

# MODULO 4: DOCKER E DEPLOY SU SERVER

## Slide 4.1: Cos'è Docker?
**Contenuto:**
Docker = "Scatole" che contengono tutto il necessario per far funzionare un programma

### Perché usarlo?
- Il bot funziona UGUALE sul tuo PC e sul server
- Ogni agente è isolato dagli altri
- Facile da avviare, fermare, aggiornare
**Stile visivo:** Container colorati come blocchi LEGO

## Slide 4.2: Installare Docker
**Contenuto:**
### Windows/Mac:
- Scarica Docker Desktop da docker.com
- Installa e avvia

### Linux (Ubuntu):
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
```

Verifica: `docker --version`

## Slide 4.3: Dockerfile - La Ricetta
**Contenuto:**
Ogni agente ha un Dockerfile che dice "come costruirlo":
```dockerfile
FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential curl git libgomp1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
```

## Slide 4.4: docker-compose.yml - L'Orchestra
**Contenuto:**
Questo file fa partire TUTTI gli agenti insieme:
```yaml
services:
  01_technical_analyzer:
    build: ./agents/01_technical_analyzer
    ports:
      - "8001:8000"
    env_file: .env
    restart: always

  04_master_ai_agent:
    build: ./agents/04_master_ai_agent
    ports:
      - "8004:8000"
    env_file: .env
    restart: always

  # ... altri agenti ...

  dashboard:
    build: ./dashboard
    ports:
      - "8080:8080"
    restart: always
```

## Slide 4.5: Comandi Docker Essenziali
**Contenuto:**
```bash
# Avvia tutto
docker-compose up -d

# Vedi i log
docker-compose logs -f orchestrator

# Ferma tutto
docker-compose down

# Ricostruisci dopo modifiche
docker-compose up -d --build

# Vedi container attivi
docker ps
```

## Slide 4.6: Scegliere un Server VPS
**Contenuto:**
Il bot deve girare 24/7, quindi serve un server cloud.

### Opzioni consigliate:
| Provider | Piano | Costo/mese |
|----------|-------|------------|
| DigitalOcean | Basic Droplet | $6 |
| Hetzner | CX11 | €4.15 |
| Contabo | VPS S | €5.99 |
| Vultr | Cloud Compute | $6 |

**Requisiti minimi:** 2GB RAM, 1 vCPU, 40GB SSD

## Slide 4.7: Setup Server Step-by-Step
**Contenuto:**
```bash
# 1. Connettiti via SSH
ssh root@IP_DEL_SERVER

# 2. Aggiorna il sistema
apt update && apt upgrade -y

# 3. Installa Docker
curl -fsSL https://get.docker.com | sh

# 4. Clona il repository
git clone https://github.com/TUO_USER/trading-agent-system.git
cd trading-agent-system

# 5. Crea file .env con le tue chiavi
nano .env

# 6. Avvia il bot!
docker-compose up -d
```

---

# MODULO 5: I NOSTRI 9 AGENTI AI

## Slide 5.1: Architettura Multi-Agente
**Contenuto:**
Il sistema è composto da agenti specializzati che lavorano insieme:
- Ogni agente fa UNA cosa bene
- L'Orchestrator li coordina
- Il Master AI prende le decisioni finali
- Il Position Manager esegue gli ordini

**Stile visivo:** Schema a blocchi con frecce di connessione, colori neon

## Slide 5.2: 01_Technical_Analyzer
**Scopo:** Analizza i grafici con indicatori tecnici

**Codice chiave (indicators.py):**
```python
class CryptoTechnicalAnalysisBybit:
    def get_complete_analysis(self, ticker: str) -> Dict:
        df = self.fetch_ohlcv(ticker, "15m", limit=200)
        
        df["ema_20"] = self.calculate_ema(df["close"], 20)
        df["ema_50"] = self.calculate_ema(df["close"], 50)
        df["rsi_14"] = self.calculate_rsi(df["close"], 14)
        df["macd_line"], df["macd_signal"], _ = self.calculate_macd(df["close"])
        
        trend = "BULLISH" if last["close"] > last["ema_50"] else "BEARISH"
        
        return {
            "symbol": ticker,
            "price": last["close"],
            "trend": trend,
            "rsi": round(last["rsi_14"], 2)
        }
```

**Endpoint:** `POST /analyze_multi_tf` → Riceve simbolo, ritorna analisi

## Slide 5.3: 03_Fibonacci_Agent
**Scopo:** Calcola livelli di supporto/resistenza Fibonacci

**Logica:**
```python
# Scarica candele a 4 ore
# Trova Swing High (massimo) e Swing Low (minimo)
# Calcola i livelli di ritracciamento

levels = {
    "0.0 (Low)": swing_low,
    "0.236": swing_low + (diff * 0.236),
    "0.382": swing_low + (diff * 0.382),
    "0.5 (Mid)": swing_low + (diff * 0.5),
    "0.618 (Golden)": swing_low + (diff * 0.618),  # Livello più importante!
    "0.786": swing_low + (diff * 0.786),
    "1.0 (High)": swing_high
}

# Se prezzo < 0.5 = DISCOUNT (zona acquisto)
# Se prezzo > 0.5 = PREMIUM (zona vendita)
```

**Stile visivo:** Grafico con livelli Fibonacci colorati

## Slide 5.4: 05_Gann_Analyzer_Agent
**Scopo:** Analisi con la teoria di W.D. Gann (cicli temporali)

**Logica:**
```python
# Trova il minimo degli ultimi 60 giorni (Start of Cycle)
low_price = df['low'].min()

# Calcola Gann Square of 9
root_low = math.sqrt(low_price)

# Livelli basati su rotazioni di 180 gradi
for i in range(1, 6):
    next_root = root_low + i
    level_price = next_root ** 2
    levels[f"Res_Level_{i}"] = level_price

# Trend:
# Se prezzo > Level 2 (360deg) = BULLISH_GANN
# Se prezzo < low = BEARISH_BREAKDOWN
# Altrimenti = ACCUMULATION
```

## Slide 5.5: 06_News_Sentiment_Agent
**Scopo:** Analizza il sentimento del mercato

**Logica:**
```python
def analyze_sentiment(symbol):
    # 1. Fear & Greed Index (dato reale da API)
    fng_val, fng_class = get_fear_and_greed()
    
    # 2. Analisi headline news (se disponibili)
    headlines = fetch_news(symbol)
    sentiment_score = TextBlob(" ".join(headlines)).sentiment.polarity
    
    # 3. Combina i segnali
    fng_normalized = (fng_val - 50) / 50  # da -1 a 1
    final_score = (fng_normalized * 0.7) + (sentiment_score * 0.3)
    
    if final_score > 0.2: return "BULLISH"
    if final_score < -0.2: return "BEARISH"
    return "NEUTRAL"
```

## Slide 5.6: 04_Master_AI_Agent ⭐ (Il Cervello)
**Scopo:** Prende le decisioni di trading usando GPT-5.1

**System Prompt:**
```python
SYSTEM_PROMPT = """
Sei un TRADER ALGORITMICO AGGRESSIVO.
Il tuo compito non è solo analizzare, è ESEGUIRE.

REGOLE CRITICHE:
1. Se l'analisi è "Bullish" e non hai posizioni -> DEVI ordinare "OPEN_LONG"
2. Se l'analisi è "Bearish" e non hai posizioni -> DEVI ordinare "OPEN_SHORT"
3. NON dire "consiglio di aprire" senza mettere l'ordine nel JSON. FALLO.
4. Leva consigliata: 5x - 7x per Scalp
5. Size consigliata: 0.15 (15% del wallet) per trade

FORMATO RISPOSTA JSON OBBLIGATORIO:
{
  "analysis_summary": "Breve sintesi del perché",
  "decisions": [
    { 
      "symbol": "ETHUSDT", 
      "action": "OPEN_LONG", 
      "leverage": 5.0, 
      "size_pct": 0.15, 
      "rationale": "RSI basso su supporto" 
    }
  ]
}
"""
```

**Stile visivo:** Cervello con connessioni neurali neon

## Slide 5.7: 07_Position_Manager
**Scopo:** Esegue gli ordini su Bybit e gestisce le posizioni

**Funzionalità chiave:**
```python
# 1. Apertura Posizione con Stop Loss automatico
res = exchange.create_order(
    symbol,
    'market',
    side,  # 'buy' o 'sell'
    qty,
    params={
        'category': 'linear',
        'stopLoss': sl_str  # Stop Loss impostato subito!
    }
)

# 2. Trailing Stop (protegge i profitti)
TRAILING_ACTIVATION_PCT = 0.018  # Attiva quando profitto > 1.8%
TRAILING_DISTANCE_PCT = 0.010   # Mantieni SL a 1% dal prezzo

def check_and_update_trailing_stops():
    for position in positions:
        if roi_pct >= TRAILING_ACTIVATION_PCT:
            # Sposta lo SL verso il profitto
            new_sl = mark_price * (1 - TRAILING_DISTANCE_PCT)
            exchange.set_trading_stop(symbol, {'stopLoss': new_sl})
```

## Slide 5.8: 08_Forecaster_Agent
**Scopo:** Previsioni di movimento futuro (base)

```python
@app.post("/forecast")
def forecast(req: ForecastRequest):
    return {
        "symbol": req.symbol,
        "forecast_bias": "NEUTRAL",
        "expected_move_pct": 0.05
    }
```
*Nota: Questo agente può essere espanso con modelli ML più avanzati*

## Slide 5.9: 09_Whale_Alert_Agent
**Scopo:** Monitora movimenti di grandi investitori (balene)

```python
async def get_whale_alerts():
    # Usa API di Whale Alert per transazioni > $10M
    r = await client.get(
        "https://api.whale-alert.io/v1/transactions",
        params={
            "min_value": 10000000,  # 10 milioni USD
            "start": int(time.time()) - 3600,  # ultima ora
            "limit": 5
        }
    )
    # Filtra solo BTC, ETH, SOL
    return [tx for tx in transactions if tx['symbol'] in ['BTC','ETH','SOL']]
```

## Slide 5.10: Orchestrator - Il Direttore d'Orchestra
**Scopo:** Coordina tutti gli agenti in un ciclo infinito

```python
async def main_loop():
    while True:
        # 1. Gestisci posizioni attive (trailing stop, ecc.)
        await manage_cycle()
        
        # 2. Analizza il mercato
        await analysis_cycle()
        
        # 3. Aspetta 15 minuti
        await asyncio.sleep(900)

async def analysis_cycle():
    # 1. Controlla wallet e posizioni aperte
    portfolio = await fetch(pos_url + "/get_wallet_balance")
    active_positions = await fetch(pos_url + "/get_open_positions")
    
    # 2. Filtra: non analizzare crypto già in portafoglio
    to_analyze = [s for s in SYMBOLS if s not in active_positions]
    
    # 3. Analisi tecnica per ogni simbolo
    for symbol in to_analyze:
        tech_data = await fetch(tech_url + "/analyze_multi_tf", {"symbol": symbol})
    
    # 4. Chiedi all'AI cosa fare
    decisions = await fetch(ai_url + "/decide_batch", {
        "global_data": portfolio,
        "assets_data": tech_data
    })
    
    # 5. Esegui le decisioni
    for decision in decisions:
        if decision.action in ["OPEN_LONG", "OPEN_SHORT"]:
            await fetch(pos_url + "/open_position", decision)
```

---

# MODULO 6: CONFIGURAZIONE E TEST

## Slide 6.1: Il File .env - Le Tue Chiavi Segrete
**Contenuto:**
```env
# Bybit API (prendi da bybit.com/user/api-management)
BYBIT_API_KEY=xxxxxxxxxxxxx
BYBIT_API_SECRET=xxxxxxxxxxxxx
BYBIT_TESTNET=true  # USA SEMPRE TESTNET ALL'INIZIO!

# OpenAI API (platform.openai.com/api-keys)
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxx

# Opzionali
COINGECKO_API_KEY=xxxxxxxxx
NEWS_API_KEY=xxxxxxxxxx
WHALE_ALERT_API_KEY=xxxxxxxxx
```

⚠️ **MAI condividere questo file!** È nel .gitignore

## Slide 6.2: Creare API Key su Bybit (TESTNET)
**Contenuto:**
1. Vai su testnet.bybit.com
2. Registrati (email diversa dal main se già registrato)
3. Vai su "API Management"
4. Crea nuova API key
5. Abilita "Contract Trade" e "Wallet"
6. Salva Key e Secret nel tuo .env

**Screenshot:** Pagina API Bybit con campi evidenziati

## Slide 6.3: Creare API Key OpenAI
**Contenuto:**
1. Vai su platform.openai.com
2. Crea account e aggiungi metodo di pagamento
3. Vai su "API Keys"
4. Clicca "Create new secret key"
5. Copia e salva nel tuo .env

**Costo:** ~$0.01 per richiesta con GPT-4o

## Slide 6.4: Primo Test Locale
**Contenuto:**
```bash
# 1. Clona il repository
git clone https://github.com/TUO_USER/trading-agent-system.git
cd trading-agent-system

# 2. Crea e configura .env
cp .env.example .env
nano .env  # inserisci le tue chiavi

# 3. Avvia con Docker
docker-compose up -d

# 4. Controlla che tutto funzioni
docker-compose logs -f

# 5. Apri la dashboard
# Browser: http://localhost:8080
```

## Slide 6.5: Verificare che gli Agenti Siano Attivi
**Contenuto:**
Ogni agente ha un endpoint `/health`. Verifica che rispondano:

| Servizio | URL | Risposta OK |
|----------|-----|-------------|
| Technical Analyzer | http://localhost:8001/health | `{"status":"active"}` |
| Fibonacci | http://localhost:8003/health | `{"status":"active"}` |
| Master AI | http://localhost:8004/health | `{"status":"active"}` |
| Gann | http://localhost:8005/health | `{"status":"active"}` |
| Sentiment | http://localhost:8006/health | `{"status":"active"}` |
| Position Manager | http://localhost:8007/health | `{"status":"active"}` |

## Slide 6.6: Passare da Testnet a Mainnet
**Contenuto:**
⚠️ **Solo quando sei sicuro che tutto funzioni!**

```env
# Prima (test con soldi finti)
BYBIT_TESTNET=true

# Dopo (soldi veri)
BYBIT_TESTNET=false
```

### Checklist prima del Mainnet:
- [ ] Testato per almeno 2 settimane su testnet
- [ ] Capisco tutti i rischi
- [ ] Ho impostato size_pct conservativa (5-10%)
- [ ] Ho attivato lo Stop Loss su tutte le posizioni
- [ ] Ho configurato alert su Telegram/Discord (opzionale)

---

# MODULO 7: DASHBOARD DI MONITORAGGIO

## Slide 7.1: La Dashboard MITRAGLIERE
**Contenuto:**
Dashboard in tempo reale per monitorare:
- Equity e saldo disponibile
- Posizioni attive con PnL
- Storico equity (grafico)
- Log dell'AI
- News di mercato

**Screenshot:** Dashboard completa con annotazioni

## Slide 7.2: Componenti della Dashboard
**Contenuto:**
```
┌─────────────────────────────────────────────────────────────┐
│  MITRAGLIERE // V7.8                        [SYSTEM ONLINE] │
├──────────────┬──────────────┬──────────────┬────────────────┤
│ NET EQUITY   │ AVAILABLE    │ SESSION PNL  │ MARKET PULSE   │
│ $1,234.56    │ $890.00      │ +$45.67      │ [News Feed]    │
├─────────────────────────────────────────────────────────────┤
│                EQUITY HISTORY (BASE: $1,000.00)             │
│  [═══════════════════════════════════════════════════════]  │
│  [         Grafico con linea verde equity               ]   │
│  [         Linea rossa tratteggiata = baseline          ]   │
├────────────────────────────┬────────────────────────────────┤
│ ACTIVE ENGAGEMENTS         │ CLOSED POSITIONS (HISTORY)     │
│ ETHUSDT (LONG) +$12.34     │ ● BTCUSDT: CLOSED with profit  │
│ SOLUSDT (SHORT) -$5.00     │ ● ETHUSDT: CLOSED with loss    │
├────────────────────────────┴────────────────────────────────┤
│ AI BRAIN LOGS              │ SYSTEM LOGS                    │
│ BTCUSDT: HOLD              │ [10:30] AI says HOLD           │
│ Reasoning: RSI neutral...  │ [10:25] ETHUSDT OPEN_LONG      │
└────────────────────────────┴────────────────────────────────┘
```

## Slide 7.3: Codice della Dashboard (FastAPI + HTML)
**Contenuto:**
```python
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import httpx

app = FastAPI(title="Mitragliere Dashboard", version="7.8.0")

POS_URL = "http://position-manager-agent:8000"
AI_URL = "http://master-ai-agent:8000"

@app.get("/api/wallet")
async def get_wallet():
    async with httpx.AsyncClient() as c:
        bal_data = await c.get(f"{POS_URL}/get_wallet_balance")
        pos_list = await c.get(f"{POS_URL}/get_open_positions")
        
        balance = bal_data.json()["balance"]
        unrealized_pnl = sum(p["pnl"] for p in pos_list.json())
        
        return {
            "equity": balance + unrealized_pnl,
            "availableToWithdraw": balance,
            "pnl_open": unrealized_pnl
        }

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return DASHBOARD_HTML  # HTML completo con CSS neon
```

## Slide 7.4: Stile CSS Neon/Crypto
**Contenuto:**
```css
:root {
    --neon-green: #00ff9d;
    --neon-red: #ff2a6d;
    --neon-blue: #00f3ff;
    --neon-yellow: #ffd700;
    --card-bg: rgba(12, 18, 24, 0.95);
}

body {
    background-color: #050505;
    color: #e0e0e0;
    font-family: 'Rajdhani', sans-serif;
}

.logo {
    font-family: 'Orbitron';
    color: var(--neon-green);
    text-shadow: 0 0 15px rgba(0,255,157,0.3);
}

.val.green { color: var(--neon-green); }
.val.red { color: var(--neon-red); }
```

---

# MODULO 8: STRATEGIE AVANZATE E OTTIMIZZAZIONE

## Slide 8.1: Ottimizzazioni v2.1
**Contenuto:**
| Componente | Prima | Dopo |
|------------|-------|------|
| Master AI | `requests` sync | `httpx` async (più veloce) |
| Sentiment | 1 chiamata per crypto | Cache 15min + batch fetch |
| API Calls | ~28.800/mese | ~2.880/mese (90% risparmio!) |

## Slide 8.2: Gestione del Rischio
**Contenuto:**
### Parametri nel codice:
```python
DEFAULT_SL_PERCENT = 0.02     # 2% Stop Loss
DEFAULT_TP_PERCENT = 0.05     # 5% Take Profit (R:R = 1:2.5)

# Break Even
BE_TRIGGER_PCT = 0.008        # +0.8% attiva il pareggio
BE_OFFSET_PCT = 0.001         # SL a +0.1% (copre commissioni)

# Trailing Stop
TRAILING_ACTIVATION_PCT = 0.018  # +1.8% attiva trailing
TRAILING_DISTANCE_PCT = 0.010    # SL segue a 1% dal prezzo
```

**Stile visivo:** Grafico con livelli SL/TP/BE evidenziati

## Slide 8.3: Personalizzare le Crypto Monitorate
**Contenuto:**
Nel file orchestrator/main.py:
```python
# Aggiungi o rimuovi simboli
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

# Esempi di espansione:
SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT",
    "AVAXUSDT", "DOTUSDT", "LINKUSDT",
    "XRPUSDT", "ADAUSDT", "MATICUSDT"
]
```

## Slide 8.4: Modificare la Strategia dell'AI
**Contenuto:**
Nel file 04_master_ai_agent/main.py, modifica il SYSTEM_PROMPT:

```python
# Più conservativo:
SYSTEM_PROMPT = """
Sei un TRADER ALGORITMICO PRUDENTE.
Apri posizioni SOLO quando tutti gli indicatori concordano.
Leva massima: 3x
Size massima: 10% del wallet
"""

# Più aggressivo:
SYSTEM_PROMPT = """
Sei un TRADER ALGORITMICO AGGRESSIVO.
Cerca opportunità anche su segnali deboli.
Leva: 7x-10x per scalping
Size: 20-25% del wallet
"""
```

## Slide 8.5: Aggiungere Nuovi Indicatori
**Contenuto:**
Nel file 01_technical_analyzer/indicators.py:

```python
# Aggiungi Bollinger Bands
from ta.volatility import BollingerBands

def calculate_bollinger(self, data, period=20):
    bb = BollingerBands(data, window=period)
    return {
        "upper": bb.bollinger_hband(),
        "middle": bb.bollinger_mavg(),
        "lower": bb.bollinger_lband()
    }

# Nel get_complete_analysis():
bb = self.calculate_bollinger(df["close"])
return {
    ...
    "bollinger": {
        "upper": round(bb["upper"].iloc[-1], 2),
        "lower": round(bb["lower"].iloc[-1], 2)
    }
}
```

## Slide 8.6: Monitoraggio Continuo
**Contenuto:**
### Comandi utili:
```bash
# Vedi log in tempo reale
docker-compose logs -f orchestrator

# Vedi solo errori
docker-compose logs -f | grep -i error

# Riavvia un singolo agente
docker-compose restart 04_master_ai_agent

# Aggiorna e riavvia tutto
git pull
docker-compose up -d --build
```

## Slide 8.7: Alert Telegram (Opzionale)
**Contenuto:**
Aggiungi notifiche al tuo telefono:
```python
import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    })

# Uso:
send_telegram("🚀 <b>OPEN LONG</b> ETHUSDT x5 a $1,850")
```

---

# MODULO BONUS: INTERAZIONE CON LLM - ESEMPI PRATICI

## Slide B.1: Esempio 1 - Chiedere un Nuovo Indicatore
**Prompt a ChatGPT:**
```
Voglio aggiungere l'indicatore Stochastic RSI al mio analizzatore tecnico.

Contesto:
- Uso Python 3.10 con la libreria 'ta'
- Ho già una classe CryptoTechnicalAnalysisBybit
- I dati sono in un DataFrame pandas con colonne: open, high, low, close, volume

Scrivi:
1. La funzione per calcolare Stochastic RSI con periodo 14
2. Come integrarla nel metodo get_complete_analysis()
3. Come interpretare i valori (quando è oversold/overbought)
```

## Slide B.2: Esempio 2 - Debugging con Claude
**Prompt a Claude:**
```
Il mio bot ha questo errore:
"ccxt.base.errors.InvalidOrder: bybit insufficient available balance"

Ecco il codice che calcola la quantità:
[incolla il codice]

Ecco i log:
[incolla i log]

Perché succede e come lo risolvo?
```

## Slide B.3: Esempio 3 - Verifica Sicurezza con Gemini
**Prompt a Gemini:**
```
Sto creando un bot di trading. Questo è il mio codice per gestire le API key:

[incolla il codice]

Domande:
1. Ci sono vulnerabilità di sicurezza?
2. Le chiavi sono protette correttamente?
3. Cosa potrei migliorare?
```

## Slide B.4: La Regola d'Oro della Competizione
**Contenuto:**
```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│   1. GENERA con ChatGPT                                     │
│          ↓                                                  │
│   2. VERIFICA con Claude                                    │
│          ↓                                                  │
│   3. OTTIMIZZA con Gemini                                   │
│          ↓                                                  │
│   4. IMPLEMENTA con Copilot                                 │
│          ↓                                                  │
│   5. TESTA e ITERA                                          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Stile visivo:** Diagramma di flusso ciclico con frecce neon

---

# CONCLUSIONE

## Slide C.1: Cosa Hai Imparato
**Contenuto:**
✅ Come funziona l'Intelligenza Artificiale e gli LLM
✅ Le basi del trading di criptovalute
✅ Python, VS Code, GitHub, Docker
✅ Come costruire un sistema multi-agente
✅ Come far "competere" diversi LLM per codice migliore
✅ Come deployare su un server 24/7
✅ Come monitorare e ottimizzare il bot

## Slide C.2: Prossimi Passi
**Contenuto:**
1. ⚗️ Testa su TESTNET per almeno 2 settimane
2. 📊 Analizza i risultati e ottimizza i parametri
3. 💰 Quando sei pronto, passa a MAINNET con capitale PICCOLO
4. 🔄 Continua a iterare e migliorare
5. 🤝 Unisciti alla community per condividere idee

## Slide C.3: Disclaimer Finale
**Contenuto:**
⚠️ **ATTENZIONE**

Il trading di criptovalute comporta RISCHI ELEVATI.
- Puoi perdere tutto il capitale investito
- I risultati passati NON garantiscono risultati futuri
- Questo corso è SOLO a scopo educativo
- NON sono un consulente finanziario
- Investi SOLO quello che puoi permetterti di perdere

**Stile visivo:** Box rosso con icona warning

## Slide C.4: Grazie!
**Contenuto:**
Hai domande?

📧 [Tua email]
💬 [Link Discord/Telegram community]
🐙 [Link GitHub repository]

**BUON TRADING CON L'AI! 🚀**

**Stile visivo:** Logo MITRAGLIERE con effetti neon, QR code per i link

---

# NOTE PER GAMMA.APP

## Istruzioni di Design
- **Font principale:** Rajdhani, Orbitron per titoli
- **Font codice:** JetBrains Mono
- **Colori primari:** #00ff9d (verde neon), #00f3ff (blu cyber), #ff2a6d (rosso alert)
- **Background:** Nero (#050505) con pattern circuiti sottili
- **Stile:** Futuristico, tech, crypto, effetti glow neon
- **Immagini:** Usare icone crypto (BTC, ETH, SOL), grafici trading, cervelli AI stilizzati

## Animazioni Suggerite
- Fade in per i blocchi di codice
- Highlight progressivo per i punti elenco
- Grafico animato per il diagramma architettura

## Elementi Interattivi
- Link cliccabili per i siti web menzionati
- Copy button per i blocchi di codice
- Accordion per sezioni opzionali

---

**FINE SCRIPT GAMMA.APP**
