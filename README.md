# 🤖 Trading Agent System v2.3 (Production Ready - Scalping Mode)

Sistema di trading automatico multi-agente per crypto su Bybit, alimentato da **DeepSeek** con strategia **scalping aggressiva ma profittevole**.

## ✨ Nuove Funzionalità v2.3 - Scalping Mode

### ⚡ High-Frequency Scalping
- **Timeframes**: 1m, 5m, 15m focus (conferma 1h opzionale)
- **Target piccoli**: 1-3% ROI con leva 3-10x
- **Stop stretti**: 1-2% SL per proteggere capitale
- **Exit rapidi**: Max 20-60 minuti in trade (time-based exit)
- **Alta frequenza**: 10-30 trade al giorno in condizioni ottimali

### 🔒 Intent ID Idempotency
- **Prevenzione duplicati**: `intent_id` univoco per ogni ordine
- **Persistent memory**: Stato salvato in `/data/trading_state.json`
- **TTL**: Intents puliti dopo 6 ore
- **Recovery-safe**: Funziona anche dopo restart

### ⏱️ Time-Based Exit
- **Chiusura automatica**: Position chiuse dopo `time_in_trade_limit_sec`
- **Monitoring continuo**: Check ogni 30 secondi
- **Default**: 40 minuti (configurabile 20-60 min)
- **Learning integration**: Eventi registrati per analisi

### 🚫 REVERSE Disabled
- **Scalping-first**: REVERSE disabilitato di default (troppo rischioso)
- **Actions**: Solo OPEN, CLOSE, HOLD
- **One-Way Mode**: Una posizione per symbol (no hedging)

### 🛡️ Guardrail Potenziati
- **CRASH_GUARD**: Block LONG se return_5m <= -0.6%, SHORT se >= +0.6%
- **INSUFFICIENT_MARGIN**: Blocco se available < 10 USDT
- **COOLDOWN**: Prevenzione revenge trading (15-30 min dopo close)
- **DRAWDOWN_GUARD**: Blocco se drawdown < -10%

📖 **Documentazione completa**: [SCALPING_MODE.md](./SCALPING_MODE.md)

## ✨ Funzionalità v2.2

### 🛡️ Crash Guard & Risk Management
- **Momentum Filters**: Blocca LONG durante dump rapidi e SHORT durante pump rapidi
- **2-Cycle Confirmation**: CRITICAL CLOSE richiede conferma su 2 cicli consecutivi
- **AI Parameters**: Leverage dinamico 3-10x e size 8-20% con validazione
- **Crash Metrics**: Analisi return_1m/5m/15m, range%, volume spike per evitare knife-catching

📖 **Documentazione**: [CRASH_GUARD_DOCUMENTATION.md](./CRASH_GUARD_DOCUMENTATION.md)

## ✨ Ottimizzazioni v2.1

| Componente | Ottimizzazione |
|------------|---------------|
| Master AI | `httpx` async invece di `requests` sync |
| Sentiment | Cache 15min + batch fetch (1 API call per tutte le crypto) |
| Orchestrator | Chiama `/refresh_all` una volta per scan |

**Risultato**: ~2.880 chiamate CoinGecko/mese invece di ~28.800 (10x risparmio)

## 🚀 Quick Start

```bash
# 1. Configura API keys
nano .env

# Aggiungi configurazione scalping (opzionale, già default)
echo "DEFAULT_TIME_IN_TRADE_LIMIT_SEC=2400" >> .env  # 40 min
echo "POSITION_MANAGER_ENABLE_REVERSE=false" >> .env
echo "BYBIT_HEDGE_MODE=false" >> .env

# 2. Avvia
docker-compose up -d

# 3. Monitora
docker-compose logs -f orchestrator

# 4. Test scalping features
python3 test_scalping_features.py
```

## 📊 Endpoints

| Servizio | URL |
|----------|-----|
| Technical | http://localhost:8001/health |
| Fibonacci | http://localhost:8002/health |
| Gann | http://localhost:8003/health |
| Sentiment | http://localhost:8004/health |
| Sentiment Cache | http://localhost:8004/cache_status |
| Master AI | http://localhost:8005/latest_decisions |
| Position Manager | http://localhost:8006/get_open_positions |

## 📈 Performance Attese (Scalping Mode)

| Metrica | Target |
|---------|--------|
| Win Rate | 55-65% |
| Trade Duration | 20-40 min |
| Daily Trades | 10-30 |
| Avg ROI/Trade | 1-3% (leveraged) |
| Max Drawdown | < 10% |

## ⚠️ Importante

- Testa con `BYBIT_TESTNET=true`
- Modello AI: DeepSeek (scalping-optimized prompt)
- One-Way Mode richiesto (`BYBIT_HEDGE_MODE=false`)
- REVERSE disabilitato per scalping
