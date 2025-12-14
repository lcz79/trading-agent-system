# Master AI Refactor - Documentazione

## Panoramica

Questa refactorizzazione rimuove le regole hardcoded dal Master AI Agent e introduce un sistema di decisione più intelligente basato su DeepSeek, con un sistema di cooldown per prevenire decisioni contraddittorie.

## Problemi Risolti

### 1. Decisioni Contraddittorie
**Prima:**
- 11:43: Chiude ETH LONG perché "trend BEARISH su tutti i TF"
- 11:44: Apre ETH LONG perché "RSI basso = rimbalzo"

**Dopo:**
- Sistema di cooldown impedisce aperture nella stessa direzione per 15 minuti
- DeepSeek riceve informazioni sulle chiusure recenti

### 2. Regole Hardcoded Rimosse
**Prima:**
```python
"Se RSI < 35 → OPEN_LONG"
"Leverage suggerito: 5x"
"Size: 15%"
```

**Dopo:**
- DeepSeek decide leverage e size in base alla confidenza (50-100%)
- Richiede almeno 3 conferme su 5 per aprire una posizione
- Nessun validator che forza limiti su leverage/size

### 3. Memoria delle Chiusure
**Prima:**
- Nessuna memoria delle posizioni chiuse di recente

**Dopo:**
- Sistema `recent_closes.json` traccia chiusure per 24 ore
- Cooldown di 15 minuti incluso nel prompt DeepSeek
- Position Manager salva automaticamente chiusure

## Nuove Funzionalità

### 1. Sistema di Cooldown

File: `/data/recent_closes.json`

```python
def save_close_event(symbol: str, side: str, reason: str):
    """Salva evento di chiusura con timestamp"""
    
def load_recent_closes(minutes: int = 15) -> List[dict]:
    """Carica chiusure negli ultimi N minuti"""
```

### 2. Raccolta Dati Completa

Il `/decide_batch` ora raccoglie dati da:
- ✅ Technical Analysis (timeframes multipli)
- ✅ Fibonacci levels
- ✅ Gann angles
- ✅ News Sentiment
- ✅ Forecast predictions

### 3. Learning Insights

Invece di imporre limiti, il Learning Agent fornisce:
- Performance recenti (win rate, PnL, drawdown)
- Pattern perdenti da evitare
- Ultimi 5 trade in perdita con contesto

### 4. Nuovo SYSTEM_PROMPT

Il prompt istruisce DeepSeek come un **trader professionista** con:

#### Conferme Richieste (almeno 3 su 5):
1. Trend concorde su almeno 2 timeframe
2. RSI in zona estrema O in direzione del trend
3. Prezzo vicino a livello chiave (Fibonacci/Gann)
4. Sentiment/news non contrario
5. Forecast concorde

#### Gestione Rischio Dinamica:
- Confidenza 90%+: leverage 10x, size 25%
- Confidenza 70-89%: leverage 5-7x, size 15-20%
- Confidenza 50-69%: leverage 3-5x, size 10-15%
- Confidenza <50%: HOLD

#### Regole di Coerenza:
- Non riaprire posizioni chiuse negli ultimi 15 minuti
- Evitare pattern storicamente perdenti
- Preferire HOLD a trade forzati

## Output JSON Esteso

```json
{
  "analysis_summary": "Sintesi ragionata",
  "decisions": [
    {
      "symbol": "ETHUSDT",
      "action": "OPEN_LONG|OPEN_SHORT|HOLD",
      "leverage": 5.0,
      "size_pct": 0.15,
      "confidence": 75,
      "rationale": "Spiegazione dettagliata",
      "confirmations": ["lista conferme trovate"],
      "risk_factors": ["lista rischi identificati"]
    }
  ]
}
```

## Integrazione con Altri Componenti

### Position Manager
Il Position Manager già implementa:
- Cooldown tracking in `/data/closed_cooldown.json`
- Auto-save delle chiusure da Bybit API
- Check cooldown prima di aprire posizioni

### Analyze Reverse
Ora salva eventi di chiusura:
```python
if action in ["CLOSE", "REVERSE"]:
    save_close_event(symbol, side, rationale)
```

## Testing

### Scenario Test: ETH Chiuso per Trend Bearish

**Prima (Bug):**
```
11:43 CLOSE "trend bearish su tutti TF"
11:44 OPEN_LONG "RSI basso su 15m"  ❌
```

**Dopo (Fix):**
```
11:43 CLOSE "trend bearish" → salvato in cooldown
11:44 DeepSeek vede: "ETH LONG chiuso 1 min fa per trend bearish"
11:44 DeepSeek decide: HOLD "Cooldown attivo, trend ancora bearish" ✅
```

### Verifica Implementazione

1. **Test Cooldown:**
```bash
# Verifica che recent_closes.json viene creato
ls -la /data/recent_closes.json

# Controlla contenuto
cat /data/recent_closes.json
```

2. **Test Decisioni AI:**
```bash
# Verifica logging decisioni con nuovi campi
cat /data/ai_decisions.json | jq '.[-1]'
```

3. **Test Performance Metrics:**
```bash
# Verifica calcolo performance
curl http://10_learning_agent:8000/performance
```

## File Modificati

1. **`agents/04_master_ai_agent/main.py`** (principale)
   - Nuovo SYSTEM_PROMPT senza regole hardcoded
   - Sistema cooldown con `save_close_event()` e `load_recent_closes()`
   - Raccolta dati completa da tutti gli agenti
   - Rimozione validatori su leverage/size
   - Nuovo modello Decision con confidence, confirmations, risk_factors

2. **Nessuna modifica necessaria:**
   - `agents/orchestrator/main.py` - già compatibile
   - `agents/07_position_manager/main.py` - già implementa cooldown
   - `agents/10_learning_agent/main.py` - API già fornisce dati necessari

## Configurazione

### Variabili Ambiente

Nessuna nuova variabile richiesta. Le seguenti sono già configurate:
- `DEEPSEEK_API_KEY` - chiave API DeepSeek
- `COOLDOWN_MINUTES` - già in Position Manager (default: 5)

### File Dati

Nuovi file creati automaticamente in `/data`:
- `recent_closes.json` - chiusure recenti per cooldown
- `ai_decisions.json` - decisioni con nuovi campi (già esistente, esteso)

## Monitoraggio

### Log da Controllare

```bash
# Master AI - cooldown saves
grep "💾 Cooldown salvato" logs/master_ai.log

# Master AI - dati raccolti
grep "✅.*data per" logs/master_ai.log

# Position Manager - cooldown check
grep "⏳ COOLDOWN" logs/position_manager.log
```

### Metriche Dashboard

La dashboard ora mostra:
- `confidence`: livello di confidenza della decisione
- `confirmations`: lista delle conferme trovate
- `risk_factors`: fattori di rischio identificati
- `source`: origine della decisione (master_ai, position_manager, etc.)

## Note Importanti

1. **Backward Compatibility**: Il sistema è retrocompatibile. Se `recent_closes.json` non esiste, funziona comunque.

2. **Performance**: Le chiamate multiple agli agenti aumentano il tempo di risposta (~5-10 secondi invece di ~2-3 secondi), ma forniscono decisioni molto più informate.

3. **Costi API**: DeepSeek riceve prompt più lunghi (2-3x), ma i costi rimangono bassissimi (~$0.001 per decisione).

4. **Fallback**: Se un agente non risponde, il sistema continua con i dati disponibili.

## Prossimi Passi

1. Monitorare le decisioni per 24-48 ore
2. Verificare che il cooldown impedisca le riaperture immediate
3. Analizzare i nuovi campi (confidence, confirmations) per pattern
4. Eventualmente adjustare COOLDOWN_MINUTES se necessario
