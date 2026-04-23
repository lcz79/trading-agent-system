#!/usr/bin/env python3
"""
LLM Signal Producer per UltraAI

Gira ogni ora come servizio separato.
Analizza il mercato usando Claude e scrive i segnali in:
  /freqtrade/user_data/llm_signals.json

Il bot UltraAI legge questo file come Layer 3 (LLM Gate).

Setup:
  export ANTHROPIC_API_KEY=sk-ant-...
  python3 producer.py

Docker:
  docker compose -f docker-compose.llm.yml up -d
"""

import os
import json
import time
import logging
from datetime import datetime, timezone
import ccxt
import anthropic

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)

PAIRS = [
    'BTC/USDC:USDC',
    'ETH/USDC:USDC',
    'SOL/USDC:USDC',
    'DOGE/USDC:USDC',
    'AVAX/USDC:USDC',
    'ADA/USDC:USDC',
    'SUI/USDC:USDC',
]

SIGNAL_FILE = os.getenv('SIGNAL_FILE', '/freqtrade/user_data/llm_signals.json')
INTERVAL_SECONDS = int(os.getenv('INTERVAL_SECONDS', '3600'))  # ogni ora
API_KEY = os.getenv('ANTHROPIC_API_KEY', '')

exchange = ccxt.hyperliquid({
    'options': {'defaultType': 'swap'},
})


def fetch_market_data(pair: str) -> dict:
    """Fetch OHLCV e calcola indicatori base."""
    try:
        ohlcv = exchange.fetch_ohlcv(pair, '1h', limit=50)
        if not ohlcv or len(ohlcv) < 20:
            return {}

        closes = [c[4] for c in ohlcv]
        highs = [c[2] for c in ohlcv]
        lows = [c[3] for c in ohlcv]
        volumes = [c[5] for c in ohlcv]

        # RSI 14
        def rsi(prices, period=14):
            gains, losses = [], []
            for i in range(1, len(prices)):
                d = prices[i] - prices[i-1]
                gains.append(max(d, 0))
                losses.append(max(-d, 0))
            avg_gain = sum(gains[-period:]) / period
            avg_loss = sum(losses[-period:]) / period
            if avg_loss == 0:
                return 100
            rs = avg_gain / avg_loss
            return round(100 - 100 / (1 + rs), 1)

        # EMA
        def ema(prices, span):
            alpha = 2 / (span + 1)
            e = prices[0]
            for p in prices[1:]:
                e = p * alpha + e * (1 - alpha)
            return round(e, 4)

        current = closes[-1]
        ema21 = ema(closes, 21)
        ema50 = ema(closes, 50)
        rsi14 = rsi(closes)

        # Variazione %
        change_1h = round((closes[-1] / closes[-2] - 1) * 100, 2)
        change_4h = round((closes[-1] / closes[-5] - 1) * 100, 2)
        change_24h = round((closes[-1] / closes[-25] - 1) * 100, 2)

        # Volume relativo
        vol_avg = sum(volumes[-20:]) / 20
        vol_ratio = round(volumes[-1] / vol_avg, 2)

        # ATR%
        trs = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
               for i in range(1, len(closes))]
        atr_pct = round(sum(trs[-14:]) / 14 / current * 100, 2)

        return {
            'pair': pair,
            'price': round(current, 4),
            'rsi_1h': rsi14,
            'ema21': ema21,
            'ema50': ema50,
            'trend': 'BULLISH' if current > ema21 > ema50 else ('BEARISH' if current < ema21 < ema50 else 'MIXED'),
            'change_1h': change_1h,
            'change_4h': change_4h,
            'change_24h': change_24h,
            'volume_ratio': vol_ratio,
            'atr_pct': atr_pct,
        }
    except Exception as e:
        log.warning(f"Fetch error {pair}: {e}")
        return {}


def get_llm_signal(client: anthropic.Anthropic, data: dict) -> dict:
    """Chiede a Claude un segnale di trading strutturato."""
    pair = data['pair']

    prompt = f"""Sei un trader professionista che analizza crypto futures su Hyperliquid.

## Dati di mercato - {pair}
- Prezzo attuale: {data['price']}
- RSI (1h): {data['rsi_1h']}
- Trend EMA (21/50): {data['trend']}
- Variazione 1h: {data['change_1h']}%
- Variazione 4h: {data['change_4h']}%
- Variazione 24h: {data['change_24h']}%
- Volume ratio (vs media 20h): {data['volume_ratio']}x
- ATR%: {data['atr_pct']}%

## Istruzioni
Analizza questi dati e fornisci un segnale di trading per le prossime 2-4 ore.
Considera: momentum, regime di mercato, volume, RSI overbought/oversold.
Sii conservativo — in caso di dubbio, NEUTRAL.

Rispondi SOLO con questo JSON (niente altro):
{{"signal": "LONG" | "SHORT" | "NEUTRAL", "confidence": 0.0-1.0, "reason": "max 20 parole"}}"""

    try:
        response = client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=100,
            messages=[{'role': 'user', 'content': prompt}]
        )
        text = response.content[0].text.strip()
        # Estrai JSON anche se c'è testo extra
        start = text.find('{')
        end = text.rfind('}') + 1
        result = json.loads(text[start:end])

        signal_map = {'LONG': 1, 'SHORT': -1, 'NEUTRAL': 0}
        signal_val = signal_map.get(result.get('signal', 'NEUTRAL'), 0)
        confidence = float(result.get('confidence', 0.5))

        # Filtra segnali a bassa confidenza
        if confidence < 0.6:
            signal_val = 0

        return {
            'signal': signal_val,
            'confidence': confidence,
            'reason': result.get('reason', ''),
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        log.warning(f"LLM error {pair}: {e}")
        return {
            'signal': 0,
            'confidence': 0.0,
            'reason': f'error: {e}',
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }


def run_cycle(client: anthropic.Anthropic):
    """Analizza tutti i pair e aggiorna il file segnali."""
    signals = {}
    results = []

    for pair in PAIRS:
        data = fetch_market_data(pair)
        if not data:
            log.warning(f"Nessun dato per {pair}, skip")
            continue

        signal = get_llm_signal(client, data)
        signals[pair] = signal
        emoji = '🟢' if signal['signal'] == 1 else ('🔴' if signal['signal'] == -1 else '⚪')
        log.info(f"{emoji} {pair}: {['SHORT','NEUTRAL','LONG'][signal['signal']+1]} "
                 f"(conf={signal['confidence']:.2f}) — {signal['reason']}")
        results.append((pair, signal))
        time.sleep(2)  # rate limit

    # Scrivi file atomicamente
    tmp_file = SIGNAL_FILE + '.tmp'
    with open(tmp_file, 'w') as f:
        json.dump(signals, f, indent=2)
    os.replace(tmp_file, SIGNAL_FILE)

    log.info(f"Segnali scritti in {SIGNAL_FILE} — {len(signals)}/{len(PAIRS)} pair analizzati")
    return signals


def main():
    if not API_KEY:
        log.error("ANTHROPIC_API_KEY non impostata. Export la variabile e riavvia.")
        return

    client = anthropic.Anthropic(api_key=API_KEY)
    log.info(f"LLM Producer avviato — intervallo: {INTERVAL_SECONDS}s")
    log.info(f"Signal file: {SIGNAL_FILE}")

    while True:
        try:
            log.info("── Nuovo ciclo di analisi ──")
            run_cycle(client)
        except KeyboardInterrupt:
            log.info("Fermato dall'utente")
            break
        except Exception as e:
            log.error(f"Errore ciclo: {e}")

        log.info(f"Prossima analisi tra {INTERVAL_SECONDS//60} minuti...")
        time.sleep(INTERVAL_SECONDS)


if __name__ == '__main__':
    main()
