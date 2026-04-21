#!/usr/bin/env python3
"""
DeepSeek Derivatives Analyst per VolatilityLimitEntryV2_fast_30m

Analizza la STRUTTURA DEL MERCATO DERIVATI (funding rate, open interest,
correlazione OI/prezzo) — dati che l'algoritmo tecnico NON usa.

Logica:
  - L'algoritmo tecnico già gestisce ADX, ATR breakout, SMA200, RSI
  - DeepSeek analizza solo: funding rate, OI change, long/short ratio,
    volume anomalie → dice se il mercato derivati SUPPORTA o CONTRADDICE
    l'ingresso long/short in questo momento

Gate nella strategia:
  - Se DeepSeek dice "mercato overextended" (longs troppo sovrappesati
    su un segnale long, o shorts sovrappesati su un segnale short)
    con conf >= 0.65 → blocca il trade
  - NEUTRAL → lascia passare

Setup:
  export DEEPSEEK_API_KEY=sk-...
  python3 producer.py

Docker:
  docker compose -f docker-compose.deepseek.yml up -d
"""

import os
import json
import time
import logging
import pandas as pd
from datetime import datetime, timezone
from openai import OpenAI
import ccxt

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)

PAIRS = [
    'BTC/USDC:USDC',
    'ETH/USDC:USDC',
    'SOL/USDC:USDC',
    'BNB/USDC:USDC',
    'XRP/USDC:USDC',
    'DOGE/USDC:USDC',
    'AVAX/USDC:USDC',
    'ADA/USDC:USDC',
    'SUI/USDC:USDC',
    'LINK/USDC:USDC',
    'DOT/USDC:USDC',
    'LTC/USDC:USDC',
    'NEAR/USDC:USDC',
    'ARB/USDC:USDC',
    'OP/USDC:USDC',
    'INJ/USDC:USDC',
    'WIF/USDC:USDC',
    'TIA/USDC:USDC',
]

SIGNAL_FILE = os.getenv('SIGNAL_FILE', '/freqtrade/user_data/deepseek_signals.json')
INTERVAL_SECONDS = int(os.getenv('INTERVAL_SECONDS', '1800'))  # 30 min
API_KEY = os.getenv('DEEPSEEK_API_KEY', '')

exchange = ccxt.hyperliquid({
    'options': {'defaultType': 'swap'},
})
exchange.load_markets()


def fetch_derivatives_data(pair: str) -> dict:
    """
    Recupera dati derivati esclusivi che l'algoritmo tecnico non usa:
    - Funding rate attuale e storico (8 periodi = ~2.7 giorni)
    - Open interest attuale
    - Variazione prezzo 1h/4h/24h per correlare con OI
    - Volume anomalia (spike rispetto alla media)
    """
    try:
        symbol = pair  # es. BTC/USDC:USDC

        # ── Funding rate ────────────────────────────────────────────────
        funding = exchange.fetch_funding_rate(symbol)
        fr_current = float(funding.get('fundingRate', 0)) * 100  # in %

        # Storia funding: ultimi 8 periodi (ogni 8h su Hyperliquid = ~2.7 giorni)
        fr_history = []
        try:
            history = exchange.fetch_funding_rate_history(symbol, limit=8)
            fr_history = [float(r['fundingRate']) * 100 for r in history if r.get('fundingRate') is not None]
        except Exception:
            pass
        fr_avg = sum(fr_history) / len(fr_history) if fr_history else fr_current
        fr_trend = fr_current - fr_avg  # positivo = funding sta salendo (più longs)

        # ── Open Interest + Premium (mark vs oracle spread) ─────────────
        oi_usd = None
        premium_pct = None
        try:
            oi_data = exchange.fetch_open_interest(symbol)
            info = oi_data.get('info', {})
            oi_amount = float(oi_data.get('openInterestAmount') or 0)
            mark_px = float(info.get('markPx') or 0)
            oracle_px = float(info.get('oraclePx') or 1)
            # OI in USD = contratti × mark price
            if oi_amount > 0 and mark_px > 0:
                oi_usd = oi_amount * mark_px
            # Premium = (mark - oracle) / oracle: positivo = longs overpriced
            if oracle_px > 0:
                premium_pct = round((mark_px - oracle_px) / oracle_px * 100, 4)
        except Exception:
            pass

        # ── OHLCV per contesto prezzo e volume ──────────────────────────
        ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=26)
        if not ohlcv or len(ohlcv) < 25:
            return {}

        df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
        price_now = float(df.iloc[-1]['close'])
        price_1h = float(df.iloc[-2]['close'])
        price_4h = float(df.iloc[-5]['close'])
        price_24h = float(df.iloc[-25]['close'])

        change_1h = round((price_now / price_1h - 1) * 100, 2)
        change_4h = round((price_now / price_4h - 1) * 100, 2)
        change_24h = round((price_now / price_24h - 1) * 100, 2)

        # Volume spike: volume ultima candela vs media ultime 24
        avg_vol = df['volume'].iloc[-25:-1].mean()
        last_vol = float(df.iloc[-1]['volume'])
        vol_ratio = round(last_vol / avg_vol, 2) if avg_vol > 0 else 1.0

        return {
            'pair': pair.split('/')[0],
            'price': round(price_now, 4),
            'funding_rate_pct': round(fr_current, 5),   # es. +0.01% = longs pagano shorts
            'funding_avg_pct': round(fr_avg, 5),         # media storica
            'funding_trend': round(fr_trend, 5),         # >0 = funding in aumento (mercato sempre più long)
            'oi_usd_M': round(oi_usd / 1e6, 2) if oi_usd else None,  # milioni USD
            'premium_pct': premium_pct,  # (mark-oracle)/oracle: >0 = longs overpriced
            'change_1h_pct': change_1h,
            'change_4h_pct': change_4h,
            'change_24h_pct': change_24h,
            'volume_ratio': vol_ratio,
        }
    except Exception as e:
        log.warning(f"Errore fetch derivati {pair}: {e}")
        return {}


def get_deepseek_signal(client: OpenAI, data: dict) -> dict:
    """
    DeepSeek analizza SOLO la struttura del mercato derivati.
    Non ripete ciò che l'algoritmo già sa (ADX, RSI, SMA200).
    Domanda: il mercato derivati SUPPORTA o CONTRADDICE un'entry in questo momento?
    """
    pair = data['pair']
    fr = data['funding_rate_pct']
    fr_avg = data['funding_avg_pct']
    fr_trend = data['funding_trend']
    vol = data['volume_ratio']
    ch1 = data['change_1h_pct']
    ch4 = data['change_4h_pct']
    ch24 = data['change_24h_pct']
    oi = data.get('oi_usd_M')
    premium = data.get('premium_pct')

    # Interpreta funding rate
    if fr > 0.05:
        fr_ctx = f"MOLTO POSITIVO ({fr:+.4f}%): longs sovrappesati, pagano shorts — risk di cascata short se prezzo scende"
    elif fr > 0.01:
        fr_ctx = f"positivo ({fr:+.4f}%): bias long moderato"
    elif fr < -0.03:
        fr_ctx = f"MOLTO NEGATIVO ({fr:+.4f}%): shorts sovrappesati, pagano longs — risk di short squeeze"
    elif fr < -0.005:
        fr_ctx = f"negativo ({fr:+.4f}%): bias short moderato"
    else:
        fr_ctx = f"neutro ({fr:+.4f}%): mercato bilanciato"

    oi_ctx = f"${oi:.1f}M" if oi else "N/D"
    trend_fr = "in AUMENTO (mercato si posiziona sempre più long)" if fr_trend > 0.005 else \
               "in CALO (mercato riduce posizioni long o va short)" if fr_trend < -0.005 else "stabile"

    premium_ctx = ""
    if premium is not None:
        if premium > 0.05:
            premium_ctx = f"\n- Mark/Oracle premium: +{premium:.4f}% (LONGS overpriced — futures scambia sopra spot, segnale di euforia short-term)"
        elif premium < -0.05:
            premium_ctx = f"\n- Mark/Oracle premium: {premium:.4f}% (SHORTS overpriced — futures sotto spot, panico short-term)"
        else:
            premium_ctx = f"\n- Mark/Oracle premium: {premium:+.4f}% (neutro)"

    prompt = f"""Sei un analista specializzato in struttura del mercato derivati crypto.
Il sistema algoritmico ha rilevato un potenziale segnale di breakout ATR su {pair}.
Il tuo compito è valutare se la struttura DERIVATI supporta o contraddice un ingresso in questo momento.

NON analizzare indicatori tecnici (RSI, ADX, SMA) — l'algoritmo li gestisce già.
Analizza SOLO questi dati derivati che l'algoritmo non usa:

## Struttura derivati {pair}
- Funding rate: {fr_ctx}
- Trend funding ultimi ~3 giorni: {trend_fr} | Media: {fr_avg:+.4f}%
- Open Interest: {oi_ctx}{premium_ctx}
- Volume: {vol:.1f}x media 24h {'⚠ SPIKE anomalo' if vol > 2.5 else '' if vol > 0.5 else '⚠ volume basso'}

## Contesto prezzo
- 1h: {ch1:+.2f}% | 4h: {ch4:+.2f}% | 24h: {ch24:+.2f}%

## Analisi richiesta
Basandoti SOLO sui derivati:
1. Funding estremo + prezzo già mosso = mercato overextended, entry rischiosa in quella direzione
2. Funding in direzione opposta al movimento = mancanza di conviction (es. prezzo sale ma funding scende)
3. Premium positivo elevato = longs overpriced, potenziale mean reversion
4. OI in crescita con prezzo = trend con conviction | OI stabile o cala = breakout debole

Bias derivati:
- LONG_OK: struttura supporta un long (funding non estremo, nessuna overextension long)
- SHORT_OK: struttura supporta uno short (nessuna overextension short)
- LONG_RISK: rischioso fare long (longs sovrappesati/overextended, funding molto positivo)
- SHORT_RISK: rischioso fare short (shorts sovrappesati, funding molto negativo)
- NEUTRAL: dati insufficienti o nessun segnale chiaro

Rispondi SOLO con JSON valido:
{{"bias": "LONG_OK"|"SHORT_OK"|"LONG_RISK"|"SHORT_RISK"|"NEUTRAL", "confidence": 0.0-1.0, "reasoning": "max 20 parole"}}

Confidence alta solo con segnali forti e chiari. NEUTRAL se ambiguo."""

    try:
        resp = client.chat.completions.create(
            model='deepseek-chat',
            messages=[{'role': 'user', 'content': prompt}],
            max_tokens=120,
            temperature=0.1,
        )
        text = resp.choices[0].message.content.strip()
        start = text.find('{')
        end = text.rfind('}') + 1
        result = json.loads(text[start:end])

        bias = result.get('bias', 'NEUTRAL')
        confidence = min(1.0, max(0.0, float(result.get('confidence', 0.5))))
        reasoning = result.get('reasoning', '')

        # Converti bias in signal numerico per compatibilità con la strategia:
        # signal=1 (LONG_OK), -1 (SHORT_OK), 0 (NEUTRAL), 2 (LONG_RISK), -2 (SHORT_RISK)
        bias_map = {
            'LONG_OK': 1,
            'SHORT_OK': -1,
            'NEUTRAL': 0,
            'LONG_RISK': 2,    # blocca long
            'SHORT_RISK': -2,  # blocca short
        }
        signal_val = bias_map.get(bias, 0)

        return {
            'signal': signal_val,
            'bias': bias,
            'confidence': confidence,
            'reasoning': reasoning,
            'funding_rate': data['funding_rate_pct'],
            'oi_usd_M': data.get('oi_usd_M'),
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        log.warning(f"DeepSeek error {pair}: {e}")
        return {
            'signal': 0,
            'bias': 'NEUTRAL',
            'confidence': 0.0,
            'reasoning': f'error: {str(e)[:50]}',
            'funding_rate': data.get('funding_rate_pct', 0),
            'oi_usd_M': data.get('oi_usd_M'),
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }


def run_cycle(client: OpenAI):
    signals = {}
    for pair in PAIRS:
        data = fetch_derivatives_data(pair)
        if not data:
            log.warning(f"Skip {pair}: nessun dato derivati")
            continue

        sig = get_deepseek_signal(client, data)
        key = f"{pair.split('/')[0]}/USDC:USDC"
        signals[key] = sig

        icon = {
            'LONG_OK': '▲',
            'SHORT_OK': '▼',
            'LONG_RISK': '⚠L',
            'SHORT_RISK': '⚠S',
            'NEUTRAL': '─',
        }.get(sig['bias'], '─')
        fr_str = f"FR={data['funding_rate_pct']:+.4f}%"
        oi_str = f"OI=${data['oi_usd_M']:.1f}M" if data.get('oi_usd_M') else "OI=N/D"
        pr_str = f"PREM={data['premium_pct']:+.4f}%" if data.get('premium_pct') is not None else ""
        log.info(f"{icon} {data['pair']:6s} {sig['bias']:10s} conf={sig['confidence']:.2f} | {fr_str} {oi_str} {pr_str}| {sig['reasoning']}")
        time.sleep(1.5)

    tmp = SIGNAL_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(signals, f, indent=2)
    os.replace(tmp, SIGNAL_FILE)
    log.info(f"Segnali scritti: {SIGNAL_FILE} ({len(signals)}/{len(PAIRS)} coppie)")
    return signals


def main():
    if not API_KEY:
        log.error("DEEPSEEK_API_KEY non impostata. Export la variabile e riavvia.")
        return

    client = OpenAI(api_key=API_KEY, base_url='https://api.deepseek.com')
    log.info(f"DeepSeek Derivatives Analyst avviato — intervallo: {INTERVAL_SECONDS//60} min")
    log.info(f"Signal file: {SIGNAL_FILE}")
    log.info(f"Coppie monitorate: {len(PAIRS)}")
    log.info("Analisi: funding rate + open interest (NON indicatori tecnici)")

    while True:
        try:
            log.info('── Nuovo ciclo derivati ──')
            run_cycle(client)
        except KeyboardInterrupt:
            log.info('Fermato')
            break
        except Exception as e:
            log.error(f'Errore ciclo: {e}')

        log.info(f'Prossima analisi tra {INTERVAL_SECONDS // 60} minuti...')
        time.sleep(INTERVAL_SECONDS)


if __name__ == '__main__':
    main()
