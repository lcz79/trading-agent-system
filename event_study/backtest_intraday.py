import os, time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import ccxt

from ta.trend import EMAIndicator, ADXIndicator
from ta.volatility import AverageTrueRange

SYMBOLS = ["BTC/USDT:USDT","ETH/USDT:USDT","SOL/USDT:USDT"]
TF_15M = "15m"
TF_1H = "1h"
DAYS = 365*3

# strategy params (from our analysis, "più trade")
MIN_ADX_1H = 20.0
MIN_ATRPCT_15M = {
    "BTC/USDT:USDT": 0.27,
    "ETH/USDT:USDT": 0.43,
    "SOL/USDT:USDT": 0.50,
}
COOLDOWN_HOURS = 2

# exits
SL_ATR_MULT = 1.3
TP_ATR_MULT = 2.0
MAX_HOLD_HOURS = 12

# costs (conservative defaults)
TAKER_FEE = 0.00055   # 0.055% per side (adjust to your Bybit tier)
SLIPPAGE = 0.00020    # 0.02% per side

OUTDIR="/data/event_study/backtest_3y"
OHLCVDIR=f"{OUTDIR}/ohlcv"
os.makedirs(OUTDIR, exist_ok=True)
os.makedirs(OHLCVDIR, exist_ok=True)

def safe_sym(s: str) -> str:
    return s.replace("/", "_").replace(":", "_")

def utc_ms(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp()*1000)

def make_ex():
    return ccxt.bybit({"enableRateLimit": True, "options":{"defaultType":"swap"}})

def fetch_all(ex, symbol, tf, since_ms, until_ms):
    all_rows=[]
    since=since_ms
    limit=1000
    while since < until_ms:
        rows=None
        try:
            rows=ex.fetch_ohlcv(symbol, timeframe=tf, since=since, limit=limit, params={"category":"linear"})
        except Exception as err:
            print(f"[fetch] {symbol} {tf} err={err} -> sleep 2s")
            time.sleep(2)
            continue
        if not rows:
            break
        all_rows.extend(rows)
        since = rows[-1][0] + 1
        time.sleep(ex.rateLimit/1000.0)

    df=pd.DataFrame(all_rows, columns=["ts","open","high","low","close","volume"]).drop_duplicates("ts").sort_values("ts")
    df["datetime"]=pd.to_datetime(df["ts"], unit="ms", utc=True)
    df=df.set_index("datetime")
    for c in ["open","high","low","close","volume","ts"]:
        df[c]=pd.to_numeric(df[c], errors="coerce")
    return df

def load_or_fetch(ex, symbol, tf, since_ms, until_ms):
    path=f"{OHLCVDIR}/{safe_sym(symbol)}_{tf}.csv"
    if os.path.exists(path):
        df=pd.read_csv(path)
        df["datetime"]=pd.to_datetime(df["datetime"], utc=True)
        df=df.set_index("datetime")
        for c in ["open","high","low","close","volume","ts"]:
            df[c]=pd.to_numeric(df[c], errors="coerce")
        # if file too short, refetch
        if len(df) > 1000:
            return df
    df=fetch_all(ex, symbol, tf, since_ms, until_ms)
    df.reset_index().to_csv(path, index=False)
    return df

def add_ind_15m(df):
    d=df.copy()
    close=d["close"]; high=d["high"]; low=d["low"]
    d["ema20"]=EMAIndicator(close, window=20).ema_indicator()
    d["atr14"]=AverageTrueRange(high=high, low=low, close=close, window=14).average_true_range()
    d["atrpct14"]=(d["atr14"]/d["close"])*100.0
    d["ema20_slope5"]=d["ema20"].diff(5)
    return d

def add_ind_1h(df):
    d=df.copy()
    close=d["close"]; high=d["high"]; low=d["low"]
    adx=ADXIndicator(high=high, low=low, close=close, window=14)
    d["adx14"]=adx.adx()
    return d

def align_1h_to_15m(df15, df1h):
    # forward-fill last known 1h adx into 15m index
    s = df1h["adx14"].copy()
    s = s.reindex(df15.index, method="ffill")
    return s

def backtest_symbol(symbol, df15, adx1h_series):
    d=df15.copy()
    d["adx1h"]=adx1h_series

    # warmup
    d = d.dropna(subset=["ema20","atr14","atrpct14","ema20_slope5","adx1h"])
    d = d.sort_index()

    in_pos=False
    side=None
    entry_price=None
    entry_time=None
    sl=None
    tp=None
    cooldown_until=None

    trades=[]

    max_hold = timedelta(hours=MAX_HOLD_HOURS)
    cooldown = timedelta(hours=COOLDOWN_HOURS)

    for t, row in d.iterrows():
        o,h,l,c = row["open"],row["high"],row["low"],row["close"]

        # manage open trade first
        if in_pos:
            exit_reason=None
            exit_price=None

            # time exit
            if t - entry_time >= max_hold:
                exit_reason="time"
                exit_price = c

            # SL/TP (assume worst-case within candle: SL hit before TP)
            if exit_reason is None:
                if side=="long":
                    if l <= sl:
                        exit_reason="sl"
                        exit_price = sl
                    elif h >= tp:
                        exit_reason="tp"
                        exit_price = tp
                else:
                    if h >= sl:
                        exit_reason="sl"
                        exit_price = sl
                    elif l <= tp:
                        exit_reason="tp"
                        exit_price = tp

            if exit_reason is not None:
                # apply slippage + fees (2 sides)
                if side=="long":
                    gross = (exit_price - entry_price) / entry_price
                else:
                    gross = (entry_price - exit_price) / entry_price

                cost = 2*TAKER_FEE + 2*SLIPPAGE
                net = gross - cost

                trades.append({
                    "symbol": symbol,
                    "side": side,
                    "entry_time": entry_time,
                    "exit_time": t,
                    "entry": entry_price,
                    "exit": exit_price,
                    "reason": exit_reason,
                    "gross_ret": gross,
                    "net_ret": net,
                })

                in_pos=False
                cooldown_until = t + cooldown
                side=None
                entry_price=None
                entry_time=None
                sl=tp=None

        # entry
        if not in_pos:
            if cooldown_until is not None and t < cooldown_until:
                continue

            # regime filters
            if row["adx1h"] < MIN_ADX_1H:
                continue
            if row["atrpct14"] < MIN_ATRPCT_15M[symbol]:
                continue

            # trend alignment
            ema20=row["ema20"]
            slope=row["ema20_slope5"]

            go_long = (c > ema20) and (slope > 0)
            go_short = (c < ema20) and (slope < 0)

            if not (go_long or go_short):
                continue

            side = "long" if go_long else "short"
            entry_time = t
            # market entry on close with slippage
            if side=="long":
                entry_price = c*(1+SLIPPAGE)
                sl = entry_price - SL_ATR_MULT*row["atr14"]
                tp = entry_price + TP_ATR_MULT*row["atr14"]
            else:
                entry_price = c*(1-SLIPPAGE)
                sl = entry_price + SL_ATR_MULT*row["atr14"]
                tp = entry_price - TP_ATR_MULT*row["atr14"]

            in_pos=True

    return pd.DataFrame(trades)

def summarize(trades: pd.DataFrame):
    if trades.empty:
        return {"trades":0}
    net = trades["net_ret"]
    eq = (1.0 + net).cumprod()
    dd = (eq/eq.cummax()-1.0).min()
    win = (net>0).mean()
    return {
        "trades": int(len(trades)),
        "winrate": float(win),
        "avg_net": float(net.mean()),
        "median_net": float(net.median()),
        "total_return": float(eq.iloc[-1]-1.0),
        "max_drawdown": float(dd),
    }

def main():
    ex=make_ex()
    until=datetime.now(timezone.utc)
    since=until - timedelta(days=DAYS)
    since_ms=utc_ms(since); until_ms=utc_ms(until)

    all_trades=[]
    for sym in SYMBOLS:
        print("== fetching", sym, "==")
        df15 = load_or_fetch(ex, sym, TF_15M, since_ms, until_ms)
        df1h = load_or_fetch(ex, sym, TF_1H, since_ms, until_ms)

        df15i = add_ind_15m(df15)
        df1hi = add_ind_1h(df1h)
        adx1h = align_1h_to_15m(df15i, df1hi)

        trades = backtest_symbol(sym, df15i, adx1h)
        all_trades.append(trades)
        rep = summarize(trades)
        print(sym, rep)

        trades.to_csv(f"{OUTDIR}/trades_{safe_sym(sym)}.csv", index=False)

    trades_all = pd.concat(all_trades, ignore_index=True)
    trades_all.to_csv(f"{OUTDIR}/trades_ALL.csv", index=False)
    print("\nALL", summarize(trades_all))
    print("WROTE:", OUTDIR)

if __name__=="__main__":
    main()
