import json, os, time
from datetime import datetime, timezone
from dateutil.parser import isoparse
from tabulate import tabulate

MEM_PATH = "data/memory_hub.json"

def load_json(path, default):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

def main():
    print("Dashboard - Premi Ctrl+C per uscire")
    while True:
        try:
            os.system("clear" if os.name != 'nt' else 'cls')
            print(f"===== MITRAGLIERE A.I. DASHBOARD (UTC: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}) =====")
            
            mem = load_json(MEM_PATH, {})
            sara = mem.get("SARA", {})
            vittoria = mem.get("VITTORIA", {}).get("GLOBAL", {})
            webby_proposals = mem.get("WEBBY", {}).get("proposals", {}).get("data", {}).get("trades", [])

            # Sezione News Sentiment
            if vittoria and 'ts' in vittoria:
                sentiment = vittoria.get("data",{}).get("sentiment", 0)
                age = (datetime.now(timezone.utc) - isoparse(vittoria["ts"])).total_seconds()
                print(f"\nNEWS Sentiment: {sentiment:.3f} (aggiornato {int(age)}s fa)")
            
            # NUOVA SEZIONE: Proposte di Trade da Webby
            print("\n--- 🎯 PROPOSTE DI TRADING ---")
            if webby_proposals:
                proposal_rows = [
                    [
                        p['symbol'], p['side'], p['entry'], p['sl'], p['tp'], 
                        f"{p['qty_est']:.2f}", p['score'], p['logic']
                    ] 
                    for p in webby_proposals
                ]
                headers = ["Asset", "Side", "Entry", "Stop Loss", "Take Profit", "Qty (Est.)", "Score", "Logic"]
                print(tabulate(sorted(proposal_rows, key=lambda r: r[6], reverse=True), headers=headers, tablefmt="github", floatfmt=".4f"))
            else:
                print("(Nessuna proposta di trade attiva. In attesa di segnali validi...)")

            # Sezione Decisioni di Sara
            print("\n--- LIVELLO DI ATTENZIONE (SCORE DI SARA) ---")
            if sara:
                sara_rows = []
                for sym, pack in sara.items():
                    dat = pack.get("data", {})
                    if 'ts' not in pack: continue
                    age = (datetime.now(timezone.utc) - isoparse(pack["ts"])).total_seconds()
                    score = dat.get("score", 0)
                    if abs(score) > 0.1: # Mostra solo se c'è un minimo di interesse
                        sara_rows.append([sym, dat.get("bias", "-"), score, f"{int(age)}s"])
                
                if sara_rows:
                    print(tabulate(sorted(sara_rows, key=lambda r: abs(r[2]), reverse=True)[:10], headers=["Asset","Bias","Score", "Age"], tablefmt="github"))
                else:
                    print("(Nessun asset con score significativo al momento)")
            
            time.sleep(10)
        except KeyboardInterrupt:
            print("\nDashboard fermata.")
            break
        except Exception as e:
            print(f"Errore dashboard: {e}")
            time.sleep(10)

if __name__=="__main__":
    main()
