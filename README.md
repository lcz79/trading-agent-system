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

# 2. Run quality checks (optional but recommended)
make check
# or: ./scripts/check.sh

# 3. Avvia
docker-compose up -d
# or: make docker-up

# 4. Monitora
docker-compose logs -f orchestrator
# or: make docker-logs

# 5. Test scalping features
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

## 🧪 Testing & Quality Control

### Quick Commands (Makefile)

```bash
# Show all available commands
make help

# Run all quality checks (syntax + tests)
make check

# Run only new tests
make test-new

# Check Python syntax
make syntax

# Clean cache files
make clean
```

### Run Automated Checks

```bash
# Run all syntax, import, and test checks
./scripts/check.sh

# Run specific test categories
python3 -m pytest -m unit         # Unit tests only
python3 -m pytest -m integration  # Integration tests
python3 -m pytest -m "not exchange"  # Skip exchange connectivity tests

# Run specific test files
python3 -m pytest test_exchange_config.py -v
python3 -m pytest test_strategy_selection.py -v
python3 -m pytest test_stop_loss_trailing.py -v
```

### Manual Syntax Check

```bash
# Check Python syntax for all files
python3 -m compileall .

# Check specific agent
python3 -m compileall agents/07_position_manager/
```

## 🔄 Exchange Configuration

### Bybit (Default)

```bash
# In .env file
EXCHANGE=bybit
BYBIT_API_KEY=your_api_key_here
BYBIT_API_SECRET=your_api_secret_here
BYBIT_TESTNET=false
```

### Hyperliquid

```bash
# In .env file
EXCHANGE=hyperliquid
HYPERLIQUID_API_KEY=your_hyperliquid_key_here
HYPERLIQUID_API_SECRET=your_hyperliquid_secret_here
HYPERLIQUID_TESTNET=false
```

**Important Notes:**
- Hyperliquid integration is implemented using ccxt but requires verification before production use
- Please verify with ccxt documentation:
  - Correct API parameter names
  - Testnet/sandbox mode configuration
  - Market loading and symbol format
- Test thoroughly on testnet before using with real funds

**Note**: The system uses a pluggable exchange factory. To switch exchanges:
1. Update the `EXCHANGE` variable in `.env`
2. Provide the appropriate API credentials
3. Restart the services: `docker-compose down && docker-compose up -d`

### Verify Exchange Connection

```bash
# Check position manager logs for exchange connection
docker-compose logs position_manager | grep "Exchange initialized"

# Should see: "✅ Exchange initialized: BYBIT" or "✅ Exchange initialized: HYPERLIQUID"
```

## 🎯 Strategy Configuration

### Active Strategy Selection

The system uses evolved parameters from the Learning Agent (`/data/evolved_params.json`). The active strategy is automatically logged at orchestrator startup.

### Verify Active Strategy

```bash
# Check orchestrator logs at startup
docker-compose logs orchestrator | grep "ACTIVE STRATEGY"

# Should show:
# ✅ Strategy Source: Learning Agent (evolved_params.json)
#    Version: 1.0
#    Last Updated: 2024-01-01T00:00:00Z
#    • Leverage: 5
#    • Size %: 0.15
#    • RSI Overbought: 70
#    • RSI Oversold: 30
```

### Strategy Parameters Location

- **Evolved Parameters**: `/data/evolved_params.json` (updated by Learning Agent every 48h)
- **Default Parameters**: Defined in `agents/04_master_ai_agent/main.py` (used if evolved params not found)

## 🛡️ Verify Trailing Stop & Stop Loss

### Check Position Manager Configuration

```bash
# View trailing stop configuration
docker-compose logs position_manager | grep -E "trailing|stop"

# Environment variables that control stop loss:
ENABLE_TRAILING_STOP=true              # Enable trailing stop (default: true)
TRAILING_ACTIVATION_RAW_PCT=0.0010     # 0.1% ROI to activate (default)
FALLBACK_TRAILING_PCT=0.0040           # 0.4% trailing distance (default)
DEFAULT_INITIAL_SL_PCT=0.04            # 4% initial stop loss (default)
```

### Verify Stop Loss is Active

```bash
# Check open positions with stop loss
docker-compose exec position_manager curl -s http://localhost:8006/get_open_positions | jq '.positions[] | {symbol, side, stop_loss, trailing_active}'

# Example output:
# {
#   "symbol": "BTCUSDT",
#   "side": "long",
#   "stop_loss": 49500.0,
#   "trailing_active": true
# }
```

### Test Stop Loss Logic

```bash
# Run stop loss and trailing stop tests
python3 -m pytest test_stop_loss_trailing.py -v

# All tests should pass, verifying:
# - Stop loss calculation
# - Trailing stop activation at ROI threshold
# - Trailing stop update as price moves
# - Breakeven protection
# - Symbol-specific minimum movements
```

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
