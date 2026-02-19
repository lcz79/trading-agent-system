import os, time
from datetime import datetime, timedelta, timezone
import pandas as pd, ccxt
from ta.trend import ADXIndicator
from ta.volatility import AverageTrueRange

SYMBOLS=["BTC/USDT:USDT","ETH/USDT:USDT","SOL/USDT:USDT"]
DAYS=365*3
TF15="15m"; TF1H="1h"

# regime
MIN_ADX_1H=25.0
MIN_ATRPCT_15M={"BTC/USDT:USDT":0.27,"ETH/USDT:USDT":0.43,"SOL/USDT:USDT":0.50}

# portfolio
INITIAL_EQUITY=10_000.0
RISK_PER_TRADE=0.005
MAX_OPEN_POSITIONS=1
COOLDOWN_HOURS=6

# trend-following exits
DONCH_N=40
TRAIL_ATR_MULT=3.0
MAX_HOLD_HOURS=24

# costs
TAKER_FEE=0.00055
SLIPPAGE=0.00020

OUTDIR="/data/event_study/backtest_portfolio_trend_3y"
OHLCVDIR=f"{OUTDIR}/ohlcv"
os.makedirs(OHLCVDIR, exist_ok=True)

def safe_sym(s): return s.replace("/","_").replace(":","_")
def utc_ms(dt): return int(dt.timestamp()*1000)
def ex(): return ccxt.bybit({"enableRateLimit":True,"options":{"defaultType":"swap"}})

def fetch_all(e, symbol, tf, since_ms, until_ms):
    all_rows=[]; since=since_ms; limit=1000
    while since < until_ms:
        try:
            rows=e.fetch_ohlcv(symbol, tf, since=since, limit=limit, params={"category":"linear"})
        except Exception as err:
            print(f"[fetch] {symbol} {tf} err={err} -> sleep 2s")
            time.sleep(2); continue
        if not rows: break
        all_rows += rows
        since = rows[-1][0]+1
        time.sleep(e.rateLimit/1000.0)
    df=pd.DataFrame(all_rows, columns=["ts","open","high","low","close","volume"]).drop_duplicates("ts").sort_values("ts")
    df["t"]=pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.set_index("t")

def load_or_fetch(e, symbol, tf, since_ms, until_ms):
    path=f"{OHLCVDIR}/{safe_sym(symbol)}_{tf}.csv"
    if os.path.exists(path):
        df=pd.read_csv(path)
        df["t"]=pd.to_datetime(df["t"], utc=True)
        return df.set_index("t")
    df=fetch_all(e, symbol, tf, since_ms, until_ms)
    df.reset_index().to_csv(path, index=False)
    return df

def add_15m(df):
    d=df.copy()
    d["atr14"]=AverageTrueRange(d["high"], d["low"], d["close"], 14).average_true_range()
    d["atrpct14"]=d["atr14"]/d["close"]*100.0
    d["donch_hi"]=d["high"].rolling(DONCH_N).max().shift(1)
    d["donch_lo"]=d["low"].rolling(DONCH_N).min().shift(1)
    return d

def add_1h(df):
    d=df.copy()
    d["adx14"]=ADXIndicator(d["high"], d["low"], d["close"], 14).adx()
    return d

def align_1h_to_15m(df15, df1h):
    return df1h["adx14"].reindex(df15.index, method="ffill")

def entry_signal(row, sym):
    if row["adx1h"] < MIN_ADX_1H: return None
    if row["atrpct14"] < MIN_ATRPCT_15M[sym]: return None
    c=row["close"]
    if c > row["donch_hi"]: return "long"
    if c < row["donch_lo"]: return "short"
    return None

def main():
    e=ex()
    until=datetime.now(timezone.utc)
    since=until - timedelta(days=DAYS)
    since_ms=utc_ms(since); until_ms=utc_ms(until)

    data={}
    for sym in SYMBOLS:
        print("== fetching", sym, "==")
        df15=add_15m(load_or_fetch(e,sym,TF15,since_ms,until_ms))
        df1h=add_1h(load_or_fetch(e,sym,TF1H,since_ms,until_ms))
        df15["adx1h"]=align_1h_to_15m(df15, df1h)
        df15=df15.dropna(subset=["atr14","atrpct14","donch_hi","donch_lo","adx1h"]).sort_index()
        data[sym]=df15

    idx=sorted(set().union(*[set(df.index) for df in data.values()]))

    equity=INITIAL_EQUITY
    eq=[]
    open_pos={}
    cd={(sym,side):None for sym in SYMBOLS for side in ["long","short"]}
    cooldown=timedelta(hours=COOLDOWN_HOURS)
    maxhold=timedelta(hours=MAX_HOLD_HOURS)
    trades=[]

    for t in idx:
        # exits + trail update
        for sym,pos in list(open_pos.items()):
            df=data[sym]
            if t not in df.index: continue
            r=df.loc[t]
            h,l,c = float(r["high"]), float(r["low"]), float(r["close"])
            side=pos["side"]

            # update trailing stop
            if side=="long":
                pos["trail_stop"]=max(pos["trail_stop"], c-pos["trail_dist"])
                hit = l <= pos["trail_stop"]
            else:
                pos["trail_stop"]=min(pos["trail_stop"], c+pos["trail_dist"])
                hit = h >= pos["trail_stop"]

            time_exit = (t - pos["entry_time"]) >= maxhold
            if not (hit or time_exit):
                continue

            exit_price = pos["trail_stop"] if hit else c
            entry=pos["entry"]; qty=pos["qty"]
            notional=entry*qty
            gross = (exit_price-entry)/entry if side=="long" else (entry-exit_price)/entry
            net = gross - (2*TAKER_FEE + 2*SLIPPAGE)
            pnl = notional*net
            equity += pnl

            trades.append({"symbol":sym,"side":side,"entry_time":pos["entry_time"],"exit_time":t,
                           "entry":entry,"exit":exit_price,"qty":qty,"notional":notional,
                           "reason":"trail" if hit else "time","gross_ret":gross,"net_ret":net,
                           "pnl_usdt":pnl,"equity_after":equity})
            cd[(sym,side)]=t+cooldown
            open_pos.pop(sym,None)

        eq.append((t,equity))

        # entries
        if len(open_pos) >= MAX_OPEN_POSITIONS:
            continue

        for sym in SYMBOLS:
            if sym in open_pos: continue
            df=data[sym]
            if t not in df.index: continue
            r=df.loc[t]
            sig=entry_signal(r,sym)
            if sig is None: continue
            if cd[(sym,sig)] is not None and t < cd[(sym,sig)]: continue

            c=float(r["close"]); atr=float(r["atr14"])
            if c<=0 or atr<=0: continue

            entry = c*(1+SLIPPAGE) if sig=="long" else c*(1-SLIPPAGE)
            trail_dist = TRAIL_ATR_MULT*atr
            trail_stop = entry-trail_dist if sig=="long" else entry+trail_dist
            risk_per_unit = abs(entry-trail_stop)
            if risk_per_unit<=0: continue

            risk_budget = equity*RISK_PER_TRADE
            qty = risk_budget/risk_per_unit

            # entry fee
            equity -= (entry*qty)*TAKER_FEE

            open_pos[sym]={"side":sig,"entry_time":t,"entry":entry,"qty":qty,
                           "trail_dist":trail_dist,"trail_stop":trail_stop}
            break

    os.makedirs(OUTDIR, exist_ok=True)
    tdf=pd.DataFrame(trades)
    eqdf=pd.DataFrame(eq, columns=["t","equity"]).set_index("t")
    tdf.to_csv(f"{OUTDIR}/trades.csv", index=False)
    eqdf.to_csv(f"{OUTDIR}/equity.csv", index=True)

    if tdf.empty:
        print("NO TRADES"); return

    total_return = eqdf["equity"].iloc[-1]/INITIAL_EQUITY - 1.0
    dd = (eqdf["equity"]/eqdf["equity"].cummax()-1.0).min()
    win = (tdf["pnl_usdt"]>0).mean()

    print("TRADES:", len(tdf))
    print("WINRATE:", float(win))
    print("PNL_USDT:", float(tdf["pnl_usdt"].sum()))
    print("TOTAL_RETURN:", float(total_return))
    print("MAX_DRAWDOWN:", float(dd))
    print("FINAL_EQUITY:", float(eqdf["equity"].iloc[-1]))
    print("WROTE:", OUTDIR)

if __name__=="__main__":
    main()
