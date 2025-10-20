import ccxt
import json
import logging

logging.basicConfig(level=logging.INFO, format='[%(asctime)s][%(levelname)s] %(message)s')

# Categorie di asset che ci interessano (con parole chiave per la ricerca)
CATEGORIES = {
    "CRYPTO": ["BTC", "ETH", "SOL"],
    "FOREX": ["EUR", "GBP", "JPY", "AUD", "CAD"],
    "INDICES": ["SPX", "NAS", "US30", "DE40", "UK100", "JP225", "HK50"],
    "METALS": ["XAU", "XAG"],
    "COMMODITIES": ["WTI", "BRENT", "NATGAS", "COPPER"]
}

def explore_markets():
    """
    Si connette a Bybit, scarica tutti i mercati di tipo 'swap' (derivati)
    e li cataloga in base alle nostre categorie di interesse.
    """
    logging.info("Avvio del Market Explorer per Bybit...")
    
    try:
        # Inizializziamo l'exchange per i derivati
        exchange = ccxt.bybit({'options': {'defaultType': 'swap'}})
        
        # Carichiamo TUTTI i mercati disponibili tramite API
        all_markets = exchange.load_markets()
        logging.info(f"Trovati {len(all_markets)} mercati totali sull'exchange.")
        
        # Estraiamo solo i simboli (i nomi dei mercati)
        all_symbols = list(all_markets.keys())
        
        found_assets = {cat: [] for cat in CATEGORIES}

        # Cerchiamo i nostri asset di interesse nella lista completa
        for category, keywords in CATEGORIES.items():
            for keyword in keywords:
                for symbol in all_symbols:
                    # Cerchiamo la parola chiave nel simbolo, assicurandoci che non sia una crypto
                    # se stiamo cercando un asset non-crypto.
                    if keyword in symbol and symbol not in found_assets[category]:
                         # Aggiungiamo il simbolo corretto e ufficiale
                         found_assets[category].append(symbol)
        
        # Rimuoviamo i duplicati e ordiniamo
        for cat in found_assets:
            found_assets[cat] = sorted(list(set(found_assets[cat])))

        # Salviamo i risultati in un file JSON per un'analisi comoda
        output_filename = "bybit_official_symbols.json"
        with open(output_filename, 'w') as f:
            json.dump(found_assets, f, indent=4)
            
        logging.info(f"✅ Ricerca completata! I simboli ufficiali sono stati salvati in '{output_filename}'")
        
        print("\n--- RIEPILOGO SIMBOLI TROVATI ---")
        for category, symbols in found_assets.items():
            print(f"\n{category}:")
            if symbols:
                for s in symbols:
                    print(f"  - {s}")
            else:
                print("  (Nessun simbolo trovato per questa categoria con le parole chiave attuali)")

    except Exception as e:
        logging.error(f"Si è verificato un errore: {e}")

if __name__ == "__main__":
    explore_markets()
