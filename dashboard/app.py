import streamlit as st

# Imposta la configurazione della pagina
st.set_page_config(
    page_title="Trading Agent System Dashboard",
    page_icon="🤖",
    layout="wide"
)

# Titolo principale del dashboard
st.title("🤖 Trading Agent System Dashboard")

# Un piccolo messaggio per farci sapere che tutto funziona
st.subheader("Il sistema è operativo.")
st.info("Il workflow su n8n è il prossimo passo. I dati delle operazioni verranno visualizzati qui.")

st.divider()

# Puoi aggiungere qui dei placeholder per il futuro
st.write("Prossimamente:")
st.write("- Grafico dell'equity line")
st.write("- Storico delle operazioni")
st.write("- Stato attuale degli agenti")
