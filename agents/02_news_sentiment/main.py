# agents/02_news_sentiment/main.py (Versione Semplificata)

import requests
import random # Useremo il caso per simulare il sentiment

def get_crypto_news(api_key: str):
    """Recupera le notizie da NewsAPI.org."""
    if not api_key or api_key == "YOUR_NEWSAPI_KEY":
        print("ERRORE: Chiave API di NewsAPI.org non valida.")
        return []

    query = "bitcoin OR ethereum OR crypto OR cryptocurrency"
    url = f"https://newsapi.org/v2/everything?q={query}&sortBy=popularity&language=en&apiKey={api_key}"
    
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        titles = [article['title'] for article in data['articles']]
        return titles
    except requests.exceptions.RequestException as e:
        print(f"Errore durante la chiamata a NewsAPI: {e}")
        return []
    except KeyError:
        print(f"Errore: La risposta da NewsAPI non ha il formato previsto. Risposta ricevuta: {data}")
        return []

def analyze_news_sentiment(news_titles: list):
    """
    ANALISI FINTA: Simula il sentiment senza usare l'intelligenza artificiale.
    Questo serve solo per testare il flusso di dati.
    """
    if not news_titles:
        return {"average_sentiment_score": 0, "sentiment_label": "NEUTRAL", "article_count": 0}

    # Simuliamo un'analisi assegnando un sentiment a caso
    labels = ["POSITIVE", "NEGATIVE", "NEUTRAL"]
    random_label = random.choice(labels)
    random_score = random.uniform(-1, 1)

    return {
        "average_sentiment_score": round(random_score, 3),
        "sentiment_label": random_label,
        "article_count": len(news_titles),
        "analysis_details": [{"article_title": title, "simulated_sentiment": random.choice(labels)} for title in news_titles]
    }

def run_full_news_analysis(api_key: str):
    """Funzione principale che orchestra il recupero e l'analisi FINTA."""
    print("Recupero delle notizie in corso...")
    news_titles = get_crypto_news(api_key)
    
    if not news_titles:
        print("Nessuna notizia trovata o errore API.")
        return analyze_news_sentiment([])

    print(f"Trovate {len(news_titles)} notizie. Esecuzione dell'analisi FINTA in corso...")
    analysis_result = analyze_news_sentiment(news_titles)
    print("Analisi FINTA completata.")
    
    return analysis_result