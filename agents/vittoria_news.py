import logging, feedparser
from textblob import TextBlob
from typing import List, Dict, Any
from core.memory_hub import publish

class VittoriaNews:
    def __init__(self, feeds: List[str], max_items: int = 5): self.feeds, self.max_items = feeds, max_items
    def collect(self) -> List[Dict]:
        out = []
        for url in self.feeds:
            try:
                feed = feedparser.parse(url)
                for e in feed.entries[: self.max_items]: out.append({"title": e.get("title","")})
            except Exception as e: logging.error(f"[VITTORIA] feed error {url}: {e}")
        return out
    def analyze(self, items: List[Dict]) -> Dict:
        if not items: return {"sentiment": 0.0, "count": 0}
        return {"sentiment": TextBlob(" ".join([i["title"] for i in items])).sentiment.polarity, "count": len(items)}
    def run(self):
        logging.info("[VITTORIA] Avvio analisi news...")
        res = self.analyze(self.collect())
        publish("VITTORIA", "GLOBAL", res)
        logging.info(f"[VITTORIA] Sentiment globale: {res['sentiment']:.3f} (da {res['count']} notizie)")