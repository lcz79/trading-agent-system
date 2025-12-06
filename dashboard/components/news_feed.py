import streamlit as st
import requests
from deep_translator import GoogleTranslator

def get_crypto_news():
    """Ottiene le ultime notizie crypto"""
    try:
        r = requests.get(
            "https://min-api.cryptocompare.com/data/v2/news/? lang=EN&categories=BTC,ETH,Trading",
            timeout=10
        )
        if r.status_code == 200:
            return r.json().get('Data', [])[:8]
    except Exception as e:
        print(f"Errore news: {e}")
    return []

def translate_to_italian(text):
    """Traduce il testo in italiano"""
    try:
        translator = GoogleTranslator(source='en', target='it')
        return translator.translate(text[:500])  # Limita per evitare errori
    except:
        return text

@st.cache_data(ttl=300)  # Cache per 5 minuti
def get_translated_news():
    """Ottiene e traduce le notizie"""
    news = get_crypto_news()
    translated = []
    
    for n in news:
        translated.append({
            'title': translate_to_italian(n.get('title', '')),
            'body': translate_to_italian(n.get('body', '')[:200] + '...'),
            'url': n.get('url', ''),
            'source': n.get('source', ''),
            'published_on': n.get('published_on', 0)
        })
    
    return translated

def render_news_feed():
    """Renderizza il feed delle notizie"""
    
    st.markdown("""
    <div class="section-header">
        <span>📰 CRYPTO NEWS</span>
        <span class="news-badge">🇮🇹 IT</span>
    </div>
    """, unsafe_allow_html=True)
    
    news = get_translated_news()
    
    if not news:
        st.caption("📡 Notizie non disponibili")
        return
    
    for n in news:
        st.markdown(f"""
        <div class="news-card">
            <div class="news-source">{n['source']}</div>
            <a href="{n['url']}" target="_blank" class="news-title">{n['title']}</a>
            <p class="news-body">{n['body']}</p>
        </div>
        """, unsafe_allow_html=True)
