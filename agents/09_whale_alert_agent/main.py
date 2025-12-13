import os
import logging
import httpx
import time
from fastapi import FastAPI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WhaleAlertAgent")

app = FastAPI()
KEY = os.getenv("WHALE_ALERT_API_KEY")

@app.get("/get_alerts")
async def whales():
    if not KEY: return {"summary": "No Key"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(
                "https://api.whale-alert.io/v1/transactions",
                params={"api_key": KEY, "min_value": 10000000, "start": int(time.time())-3600, "limit": 5}
            )
            if r.status_code == 200:
                data = r.json()
                txs = data.get("transactions", []) if data else []
                summary = ", ".join([
                    f"{t.get('symbol', 'UNKNOWN')} ${t.get('amount_usd', 0)//1000000}M" 
                    for t in txs 
                    if t.get('symbol') in ['BTC','ETH','SOL'] and t.get('amount_usd')
                ])
                return {"summary": summary if summary else "Quiet"}
    except Exception as e:
        logger.warning(f"Whale Alert API error: {e}")
    return {"summary": "API Error"}

if __name__=="__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
