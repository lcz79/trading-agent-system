# 🔄 Trading Agent System - Workflow Aggiornato (v2)

## 📊 Modifiche dalla Versione Precedente

### Agenti Rimossi
- ❌ **Agent 02 (News Sentiment/CoinGecko)** - Rimosso dalla nuova architettura
- ❌ **Agent 06 (Order Executor)** - Logica integrata direttamente nel workflow

### Agenti Aggiunti
- ✅ **Agent 07 (Position Manager)** - Gestione trailing stop e posizioni aperte

### Agenti Aggiornati
- 🔄 **Agent 01 (Technical Analyzer)** - Nuovo endpoint `/analyze_multi_tf` per analisi multi-timeframe
- 🔄 **Agent 03 (Fibonacci)** - Endpoint aggiornato `/analyze_fibonacci`
- 🔄 **Agent 04 (Master AI)** - Endpoint `/decide` con logica migliorata
- 🔄 **Agent 05 (Gann)** - Endpoint aggiornato `/analyze_gann`

## 🏗️ Nuova Struttura del Workflow

```
[Every 15 Minutes Trigger]
    ↓
    ├─→ Technical Analyzer (Multi-TF) ─┐
    ├─→ Fibonacci Analyzer ────────────┤
    └─→ Gann Analyzer ─────────────────┴─→ [Merge] 
                                              ↓
                                    [Prepare Data for AI]
                                              ↓
                                    [Master AI Decision]
                                              ↓
                                    [Should Open Position?]
                                          ↙        ↘
                              [Execute Trade]   [No Action]
                                          ↘        ↙
                                    [Position Manager]
                                    (Trailing Stop)
```

## 🔧 Endpoint degli Agenti

### 1. Technical Analyzer Agent
- **Container**: `trading-agent-system-technical-analyzer-agent-1`
- **Endpoint**: `POST /analyze_multi_tf`
- **Payload**: `{ "symbol": "BTCUSDT" }`
- **Risposta**: Analisi multi-timeframe (1h, 4h, 1d)

### 2. Fibonacci Cyclical Agent
- **Container**: `trading-agent-system-fibonacci-cyclical-agent-1`
- **Endpoint**: `POST /analyze_fibonacci`
- **Payload**: `{ "crypto_symbol": "BTCUSDT" }`
- **Risposta**: Livelli di Fibonacci e analisi ciclica

### 3. Gann Analyzer Agent
- **Container**: `trading-agent-system-gann-analyzer-agent-1`
- **Endpoint**: `POST /analyze_gann`
- **Payload**: `{ "symbol": "BTCUSDT" }`
- **Risposta**: Analisi geometrica Gann

### 4. Master AI Agent
- **Container**: `trading-agent-system-master-ai-agent-1`
- **Endpoint**: `POST /decide`
- **Payload**: 
  ```json
  {
    "symbol": "BTCUSDT",
    "tech_data": {...},
    "fib_data": {...},
    "gann_data": {...},
    "sentiment_data": {}
  }
  ```
- **Risposta**: Decisione (OPEN_LONG, OPEN_SHORT, WAIT) con trade setup

### 5. Position Manager Agent (NUOVO!)
- **Container**: `trading-agent-system-position-manager-agent-1`
- **Endpoint**: `POST /manage`
- **Payload**: `{ "positions": [] }`
- **Risposta**: Azioni di gestione posizioni con trailing stop ATR-based

## 📋 Funzionalità del Nuovo Workflow

### ✅ Cosa fa il workflow:

1. **Analisi Parallela**: Esegue le analisi tecniche, Fibonacci e Gann in parallelo
2. **Merge Intelligente**: Combina tutte le analisi senza necessità di field matching
3. **Preparazione Dati**: Identifica automaticamente ogni tipo di analisi
4. **Decisione AI**: Il Master AI Agent valuta tutti i dati e decide
5. **Esecuzione Condizionale**: Apre posizioni solo se `OPEN_LONG` o `OPEN_SHORT`
6. **Gestione Posizioni**: Il Position Manager aggiusta gli stop loss con trailing ATR

### 🆕 Novità Principali:

- **No Sentiment Agent**: La nuova versione non include l'agente CoinGecko/News
- **Esecuzione Integrata**: La logica di esecuzione è nel workflow (no agent separato)
- **Position Management**: Trailing stop automatico basato su ATR
- **Multi-Timeframe**: Analisi tecnica su più timeframe (1h, 4h, 1d)

## ⚙️ Configurazione

### Docker Compose
Assicurati che `docker-compose.yml` includa:
- `technical-analyzer-agent`
- `fibonacci-cyclical-agent`
- `gann-analyzer-agent`
- `master-ai-agent`
- **Non** include più `coingecko-agent` o `order-executor-agent` come servizi separati

### Variabili d'Ambiente
```bash
OPENAI_API_KEY=<your-openai-key>
BYBIT_API_KEY=<your-bybit-key>
BYBIT_API_SECRET=<your-bybit-secret>
```

## 🚀 Come Usare

1. **Importa il workflow**: Copia `n8n_complete_workflow.json` in n8n v1.45.1
2. **Verifica container**: `docker-compose ps` - assicurati che tutti gli agenti siano up
3. **Test manuale**: Esegui il workflow manualmente prima di attivarlo
4. **Attiva**: Toggle "Active" su ON per esecuzione automatica ogni 15 minuti

## ⚠️ Note Importanti

- **Mainnet Ready**: Questo workflow è progettato per Bybit mainnet (soldi reali)
- **Position Manager**: Gestisce automaticamente le posizioni con trailing stop
- **No News**: La versione attuale non include analisi sentiment/news
- **Auto-execution**: Il workflow esegue automaticamente i trade se l'AI decide OPEN_LONG/SHORT

## 📊 Compatibilità

- ✅ n8n v1.45.1
- ✅ Merge node typeVersion 2.1
- ✅ HTTP nodes typeVersion 4.2
- ✅ Code nodes typeVersion 2
- ✅ Bybit API v5

---

**Ultima aggiornamento**: Novembre 2025 - Versione 2.0
