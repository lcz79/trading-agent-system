# Trading Agent System - N8N Workflow

## 📋 Descrizione

Questo file contiene il workflow completo per orchestrare tutti gli agenti del Trading Agent System tramite N8N.

## 🎯 Caratteristiche del Workflow

### Schedulazione Automatica
- **Agenti operativi ogni 15 minuti:**
  - Technical Analyzer Agent (analisi RSI, MACD, medie mobili)
  - Fibonacci Cyclical Agent (ritracciamenti e estensioni di Fibonacci)
  - Gann Analyzer Agent (analisi geometrica e angoli di Gann)

- **Agente operativo ogni ora:**
  - CoinGecko News Agent (sentiment delle news e dati di mercato)
  - **Nota importante:** Il CoinGecko agent ha un trigger separato che opera ogni ora per:
    - Ottimizzare le chiamate API e rispettare i rate limits
    - Ridurre i costi delle API calls
    - Le news non cambiano così frequentemente da richiedere aggiornamenti ogni 15 minuti

### Flusso di Lavoro

1. **Trigger di Schedulazione**
   - Due schedule trigger separati per gestire intervalli diversi
   - 15 minuti per analisi tecniche
   - 1 ora per analisi news/sentiment

2. **Raccolta Analisi in Parallelo**
   - Gli agenti di analisi tecnica vengono eseguiti in parallelo ogni 15 minuti
   - L'agente CoinGecko viene eseguito separatamente ogni ora
   - Tutti i risultati vengono mergiati insieme

3. **Preparazione Dati**
   - Un nodo Code prepara i dati nel formato richiesto dal Master AI Agent
   - Include lo stato del portafoglio (capitale totale, disponibile, rischio max per trade)

4. **Decisione AI**
   - Master AI Agent analizza tutte le informazioni
   - Produce un piano di trading completo (BUY/SELL/HOLD)
   - Include position sizing, stop loss e take profit

5. **Esecuzione Ordini**
   - Se la decisione è BUY o SELL, l'ordine viene preparato ed eseguito
   - Se la decisione è HOLD, non viene eseguita nessuna azione
   - L'Order Executor Agent comunica con l'exchange (testnet di default)

6. **Logging**
   - Viene salvato un timestamp dell'ultima esecuzione

## 📥 Come Importare il Workflow in N8N

### Metodo 1: Import da File (Consigliato)

1. Apri N8N (di default su `http://localhost:5678`)
2. Fai login con le credenziali configurate
3. Clicca sul pulsante **"+"** per creare un nuovo workflow
4. Clicca sui tre puntini in alto a destra
5. Seleziona **"Import from File"**
6. Carica il file `n8n_complete_workflow.json`

### Metodo 2: Import da Clipboard

1. Apri il file `n8n_complete_workflow.json`
2. Copia **tutto** il contenuto del file (Ctrl+A, Ctrl+C)
3. Apri N8N (di default su `http://localhost:5678`)
4. Fai login con le credenziali configurate
5. Clicca sul pulsante **"+"** per creare un nuovo workflow
6. Clicca sui tre puntini in alto a destra
7. Seleziona **"Import from URL / Clipboard"**
8. Incolla il JSON copiato
9. Clicca su **"Import"**

## ⚙️ Configurazione

### Prima di Attivare il Workflow

1. **Verifica che tutti i container Docker siano attivi:**
   ```bash
   docker-compose up -d
   docker-compose ps
   ```

2. **Verifica che le variabili d'ambiente siano configurate:**
   - `OPENAI_API_KEY` - per Master AI Agent
   - `COINGECKO_API_KEY` - per CoinGecko Agent
   - `EXCHANGE_API_KEY` - per Order Executor Agent
   - `EXCHANGE_API_SECRET` - per Order Executor Agent

3. **Configura i parametri del portafoglio:**
   Nel nodo "Prepare Data for Master AI", modifica i valori in base alle tue esigenze:
   ```javascript
   portfolio_state: {
     total_capital_eur: 10000.0,        // Capitale totale in EUR
     available_capital_eur: 10000.0,    // Capitale disponibile in EUR
     max_risk_per_trade_percent: 1.0    // Rischio massimo per trade (1%)
   }
   ```

4. **Modifica il simbolo di trading (opzionale):**
   Di default il workflow opera su `BTCUSDT`. Per cambiare simbolo, modifica il campo `symbol` in tutti i nodi HTTP Request.

### Attivazione del Workflow

1. Apri il workflow importato in N8N
2. Verifica tutte le connessioni tra i nodi
3. **IMPORTANTE**: Fai un test manuale prima di attivarlo:
   - Clicca su "Execute Workflow" in alto a destra
   - Verifica che tutti i nodi vengano eseguiti correttamente
   - Controlla i log di output di ogni nodo
4. Una volta verificato che funziona correttamente, attiva il workflow:
   - Toggle "Active" in alto a destra su ON

### ⏰ Comportamento della Schedulazione

**NOTA IMPORTANTE:** Quando attivi il workflow:
- Il trigger "Every 15 Minutes" eseguirà SOLO gli agenti tecnici (Technical, Fibonacci, Gann)
- Il trigger "Every Hour (CoinGecko)" eseguirà SOLO il CoinGecko agent
- Queste sono **due esecuzioni separate** del workflow che si combinano al nodo "Merge"

**Implicazioni:**
- Ogni 15 minuti: verranno eseguite analisi tecniche, ma senza dati di news (verrà usato l'ultimo dato disponibile di CoinGecko dal merge)
- Ogni ora (ogni 4° esecuzione): verrà eseguito anche il CoinGecko agent con dati aggiornati

Questo design è ottimale perché:
- Le analisi tecniche richiedono aggiornamenti frequenti (15 minuti)
- Le news e il sentiment non cambiano così rapidamente (1 ora è sufficiente)
- Si ottimizzano le chiamate API di CoinGecko evitando costi e rate limits

## 🏗️ Struttura dei Nodi

Il workflow utilizza **due trigger separati** per gestire intervalli di esecuzione diversi:

### Trigger 1: Ogni 15 Minuti (Agenti Tecnici)
```
[Every 15 Minutes] ─┬─> [1. Technical Analyzer] ───┐
                    ├─> [2. Fibonacci Analyzer] ───┤
                    └─> [3. Gann Analyzer] ─────────┴─> [Merge All Analyses] ─┐
                                                                                 │
```

### Trigger 2: Ogni Ora (CoinGecko)
```
[Every Hour (CoinGecko)] ──> [4. CoinGecko News] ──────────> [Merge All Analyses] ─┐
                                                                                      │
```

### Flusso di Decisione ed Esecuzione
```
[Merge All Analyses] ─> [5. Prepare Data] ─> [6. Master AI Decision] ─> [Is BUY or SELL?] ─┬─> [Prepare Order] ─> [7. Execute Order]
                                                                                             │
                                                                                             └─> [No Action (HOLD)]
```

**Come Funziona:**
1. Gli agenti tecnici (Technical, Fibonacci, Gann) si eseguono ogni 15 minuti
2. Il CoinGecko agent si esegue ogni ora su un trigger separato
3. Tutti i risultati vengono mergiati nel nodo "Merge All Analyses"
4. I dati vengono preparati e inviati al Master AI Agent per la decisione
5. Se la decisione è BUY o SELL, viene eseguito un ordine
6. Se la decisione è HOLD, non viene eseguita alcuna azione

## 🔧 Personalizzazione

### Cambiare gli Intervalli di Schedulazione

**Per gli agenti tecnici (15 minuti):**
1. Clicca sul nodo "Schedule Every 15 Minutes"
2. Modifica il parametro `minutesInterval` con il valore desiderato

**Per l'agente CoinGecko (1 ora):**
1. Clicca sul nodo "Schedule Every Hour"
2. Modifica il parametro `hoursInterval` con il valore desiderato

### Aggiungere Altri Simboli

Per operare su più criptovalute contemporaneamente:
1. Duplica l'intero workflow
2. Cambia il simbolo in tutti i nodi HTTP Request
3. Rinomina il workflow per identificarlo facilmente

### Modificare la Logica di Decisione

La logica di decisione è gestita dal Master AI Agent (GPT-4). Per modificarla:
1. Modifica il file `agents/04_master_ai_agent/main.py`
2. Ricostruisci il container Docker:
   ```bash
   docker-compose build master-ai-agent
   docker-compose up -d master-ai-agent
   ```

### Note Tecniche

**Identificazione dei Dati:**
Il nodo "Prepare Data" identifica i tipi di analisi attraverso la presenza di campi specifici:
- Technical: presenza di campo `RSI`
- Fibonacci: presenza di campo `current_level`
- Gann: presenza di campo `trend`
- CoinGecko: presenza di campo `id`

Se modifichi la struttura delle risposte degli agenti, aggiorna anche questo nodo.

**Compatibilità N8N:**
Il workflow usa versioni diverse di nodi (4.2, 4.3) che sono tutte compatibili con N8N. Questo è intenzionale e supportato dalla piattaforma.

## 🐛 Troubleshooting

### Il workflow non si attiva
- Verifica che N8N sia in esecuzione: `docker-compose ps`
- Controlla i log di N8N: `docker-compose logs n8n`

### Errori di connessione agli agenti
- Verifica che tutti i container siano up: `docker-compose ps`
- Controlla i nomi dei container nel workflow corrispondano a quelli in docker-compose.yml
- Verifica la rete Docker: `docker network inspect trading-agent-system_trading_network`

### CoinGecko API restituisce errori
- Verifica che la variabile `COINGECKO_API_KEY` sia impostata correttamente
- Controlla di non aver superato i rate limits dell'API
- Verifica i log del container: `docker-compose logs coingecko-agent`

### Master AI Agent restituisce sempre HOLD
- Verifica che `OPENAI_API_KEY` sia configurata correttamente
- Controlla i log: `docker-compose logs master-ai-agent`
- Verifica il saldo del tuo account OpenAI

### Order Executor Agent non esegue ordini
- Verifica di essere in modalità `testnet` nel docker-compose.yml
- Controlla che `EXCHANGE_API_KEY` e `EXCHANGE_API_SECRET` siano configurati
- Verifica i log: `docker-compose logs order-executor-agent`

## 📊 Monitoraggio

### Log di Esecuzione N8N
Per vedere lo storico delle esecuzioni:
1. Vai su N8N
2. Clicca su "Executions" nella sidebar sinistra
3. Seleziona il workflow "Trading Agent System - Complete Workflow"

### Log dei Container
```bash
# Tutti i log
docker-compose logs -f

# Log di un singolo agente
docker-compose logs -f technical-analyzer-agent
docker-compose logs -f master-ai-agent
docker-compose logs -f order-executor-agent
```

## ⚠️ Sicurezza

1. **IMPORTANTE**: Il workflow è configurato di default per operare in modalità **testnet**
2. Prima di passare al mainnet:
   - Testa estensivamente in testnet
   - Verifica tutti gli ordini e le logiche
   - Inizia con capitale ridotto
3. Non committare mai le API keys nel repository
4. Usa sempre file `.env` per le variabili sensibili

## 📞 Supporto

Per problemi o domande:
1. Controlla i log dei container
2. Verifica che tutte le variabili d'ambiente siano configurate
3. Assicurati che tutti i container siano in esecuzione
4. Consulta la documentazione di N8N: https://docs.n8n.io/

## 🚀 Prossimi Passi

1. Importare il workflow in N8N
2. Testare manualmente l'esecuzione
3. Attivare il workflow
4. Monitorare le prime esecuzioni
5. Ottimizzare i parametri in base ai risultati

---

**DISCLAIMER**: Questo sistema è fornito per scopi educativi. Il trading di criptovalute comporta rischi significativi. Non investire mai più di quanto sei disposto a perdere.
