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

# Strategy ("più trade")
MIN_ADX_1H = 20.0
MIN_ATRPCT_15M = {
    "BTC/USDT:USDT": 0.27,
    "ETH/USDT:USDT": 0.43,
    "SOL/USDT:USDT": 0.50,
}
COOLDOWN_HOURS = 2

# Exits
SL_ATR_MULT = 1.3
TP_ATR_MULT = 2.0
MAX_HOLD_HOURS = 12

# Costs
TAKER_FEE = 0.00055   # per side
SLIPPAGE = 0.00020    # per side

# Portfolio realism
INITIAL_EQUITY = 10_000.0
RISK_PER_TRADE = 0.005       # 0.5% equity risked to SL
MAX_OPEN_POSITIONS = 2       # across symbols
ALLOW_ONE_PER_SYMBOL = True

OUTDIR="/data/event_study/backtest_portfolio_3y"
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
        try:
            rows=ex.fetch_ohlcv(symbol, timeframe=tf, since=since, limit=limit, params={"category":"linear"})
        except Exception as err:
            print(f"[fetch] {symbol} {tf} err={err} -> sleep 2s")
            time.sleep(2); continue
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
    s = df1h["adx14"].copy()
    return s.reindex(df15.index, method="ffill")

def build_master_frame(data_by_sym):
    # outer join all symbol 15m frames on datetime
    idx=None
    for sym,df in data_by_sym.items():
        idx = df.index if idx is None else idx.union(df.index)
    idx = idx.sort_values()
    return idx

def entry_signal(row, sym):
    # regime
    if row["adx1h"] < MIN_ADX_1H: return None
    if row["atrpct14"] < MIN_ATRPCT_15M[sym]: return None
    c=row["close"]; ema=row["ema20"]; slope=row["ema20_slope5"]
    if pd.isna(c) or pd.isna(ema) or pd.isna(slope): return None
    if (c > ema) and (slope > 0): return "long"
    if (c < ema) and (slope < 0): return "short"
    return None

def main():
    ex=make_ex()
    until=datetime.now(timezone.utc)
    since=until - timedelta(days=DAYS)
    since_ms=utc_ms(since); until_ms=utc_ms(until)

    data={}
    for sym in SYMBOLS:
        print("== fetching", sym, "==")
        df15 = load_or_fetch(ex, sym, TF_15M, since_ms, until_ms)
        df1h = load_or_fetch(ex, sym, TF_1H, since_ms, until_ms)
        df15i = add_ind_15m(df15)
        df1hi = add_ind_1h(df1h)
        df15i["adx1h"] = align_1h_to_15m(df15i, df1hi)
        df15i = df15i.dropna(subset=["ema20","atr14","atrpct14","ema20_slope5","adx1h"]).sort_index()
        data[sym]=df15i

    master_idx = build_master_frame(data)
    equity = INITIAL_EQUITY
    equity_curve=[]

    cooldown_until = { (sym,side): None for sym in SYMBOLS for side in ["long","short"] }
    open_pos = {}  # sym -> dict

    max_hold = timedelta(hours=MAX_HOLD_HOURS)
    cooldown = timedelta(hours=COOLDOWN_HOURS)

    trades=[]

    for t in master_idx:
        # 1) update existing positions (check exits on their symbol candle if exists)
        to_close=[]
        for sym, pos in list(open_pos.items()):
            df = data[sym]
            if t not in df.index:
                continue
            row=df.loc[t]
            o,h,l,c = row["open"],row["high"],row["low"],row["close"]

            side=pos["side"]
            exit_reason=None
            exit_price=None

            if t - pos["entry_time"] >= max_hold:
                exit_reason="time"
                exit_price=c

            if exit_reason is None:
                if side=="long":
                    if l <= pos["sl"]:
                        exit_reason="sl"; exit_price=pos["sl"]
                    elif h >= pos["tp"]:
                        exit_reason="tp"; exit_price=pos["tp"]
                else:
                    if h >= pos["sl"]:
                        exit_reason="sl"; exit_price=pos["sl"]
                    elif l <= pos["tp"]:
                        exit_reason="tp"; exit_price=pos["tp"]

            if exit_reason is not None:
                # realized PnL on notional
                entry=pos["entry"]
                qty=pos["qty"]
                notional = entry*qty

                if side=="long":
                    gross = (exit_price-entry)/entry
                else:
                    gross = (entry-exit_price)/entry

                cost = 2*TAKER_FEE + 2*SLIPPAGE
                net = gross - cost
                pnl = notional*net

                equity += pnl

                trades.append({
                    "symbol": sym,
                    "side": side,
                    "entry_time": pos["entry_time"],
                    "exit_time": t,
                    "entry": entry,
                    "exit": exit_price,
                    "qty": qty,
                    "notional": notional,
                    "reason": exit_reason,
                    "gross_ret": gross,
                    "net_ret": net,
                    "pnl_usdt": pnl,
                    "equity_after": equity,
                })

                cooldown_until[(sym,side)] = t + cooldown
                to_close.append(sym)

        for sym in to_close:
            open_pos.pop(sym, None)

        # 2) equity curve snapshot (mark-to-market omitted; realized-only curve)
        equity_curve.append((t, equity))

        # 3) entries (if capacity)
        if len(open_pos) >= MAX_OPEN_POSITIONS:
            continue

        # simple priority: evaluate symbols in fixed order
        for sym in SYMBOLS:
            if len(open_pos) >= MAX_OPEN_POSITIONS:
                break
            if ALLOW_ONE_PER_SYMBOL and sym in open_pos:
                continue
            df=data[sym]
            if t not in df.index:
                continue
            row=df.loc[t]
            sig = entry_signal(row, sym)
            if sig is None:
                continue

            # cooldown per symbol+direction
            cd = cooldown_until[(sym,sig)]
            if cd is not None and t < cd:
                continue

            c=float(row["close"])
            atr=float(row["atr14"])
            if atr <= 0 or c <= 0:
                continue

            # position sizing by risk-to-SL
            if sig=="long":
                entry = c*(1+SLIPPAGE)
                sl = entry - SL_ATR_MULT*atr
                tp = entry + TP_ATR_MULT*atr
                risk_per_unit = entry - sl
            else:
                entry = c*(1-SLIPPAGE)
                sl = entry + SL_ATR_MULT*atr
                tp = entry - TP_ATR_MULT*atr
                risk_per_unit = sl - entry

            if risk_per_unit <= 0:
                continue

            risk_budget = equity * RISK_PER_TRADE
            qty = risk_budget / risk_per_unit  # linear contracts size approximation

            # apply taker fee on entry (optional realism)
            equity -= (entry*qty)*TAKER_FEE

            open_pos[sym]={
                "side": sig,
                "entry_time": t,
                "entry": entry,
                "sl": sl,
                "tp": tp,
                "qty": qty,
            }

    trades_df=pd.DataFrame(trades)
    eq_df=pd.DataFrame(equity_curve, columns=["t","equity"]).set_index("t")

    trades_df.to_csv(f"{OUTDIR}/trades.csv", index=False)
    eq_df.to_csv(f"{OUTDIR}/equity.csv")

    if trades_df.empty:
        print("NO TRADES")
        return

    net = trades_df["pnl_usdt"].sum()
    total_ret = (eq_df["equity"].iloc[-1]/INITIAL_EQUITY)-1.0
    dd = (eq_df["equity"]/eq_df["equity"].cummax()-1.0).min()
    win = (trades_df["pnl_usdt"]>0).mean()

    print("TRADES:", len(trades_df))
    print("WINRATE:", float(win))
    print("PNL_USDT:", float(net))
    print("TOTAL_RETURN:", float(total_ret))
    print("MAX_DRAWDOWN:", float(dd))
    print("FINAL_EQUITY:", float(eq_df["equity"].iloc[-1]))
    print("WROTE:", OUTDIR)

if __name__=="__main__":
    main()
