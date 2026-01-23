# 🎬 Come Usare GAMMA.APP per Creare il Corso

## Cos'è GAMMA.APP?

GAMMA.APP è uno strumento AI che genera presentazioni automaticamente dal testo. È perfetto per creare slide professionali velocemente.

## 🚀 Passo 1: Accedi a GAMMA.APP

1. Vai su https://gamma.app
2. Clicca su "Sign Up" o "Log In"
3. Puoi usare Google, email o altri metodi

## 📝 Passo 2: Crea una Nuova Presentazione

1. Clicca su **"Create New"**
2. Seleziona **"Paste in text"** (incolla testo)
3. Qui incollerai il contenuto del corso

## 📋 Passo 3: Copia il Contenuto

### Metodo 1: Modulo per Modulo (Consigliato)

Per evitare che GAMMA faccia confusione, è meglio creare una presentazione per modulo:

1. Apri `GAMMA_APP_SCRIPT_COMPLETO.md`
2. Copia SOLO il contenuto del **Modulo 0**
3. Incolla in GAMMA
4. Genera le slide
5. Ripeti per ogni modulo

### Metodo 2: Tutto Insieme

Se preferisci avere tutto in un'unica presentazione:

1. Copia TUTTO il file markdown
2. Incolla in GAMMA
3. Seleziona "Long-form" o "Detailed" per generare più slide

## 🎨 Passo 4: Seleziona il Tema

Dopo aver incollato il testo, GAMMA ti chiederà di scegliere un tema.

### Tema Consigliato:

1. Cerca temi **"Dark"** o **"Tech"**
2. Preferisci sfondi neri/scuri
3. Se possibile, personalizza i colori:
   - Colore primario: `#00ff9d` (verde neon)
   - Colore secondario: `#00f3ff` (blu cyber)
   - Colore accent: `#ff2a6d` (rosso)

## ✏️ Passo 5: Personalizza le Slide

Dopo la generazione, rivedi ogni slide:

### Per le Slide di Codice:
- Assicurati che il codice sia in un blocco `code`
- Usa font monospace (GAMMA lo fa automaticamente)

### Per le Slide con Tabelle:
- GAMMA dovrebbe creare tabelle automaticamente
- Se non funziona, ricrea manualmente

### Per le Slide con Diagrammi:
- Usa l'editor di GAMMA per creare diagrammi
- O importa immagini che crei con altri tool (Figma, Canva)

## 📸 Passo 6: Aggiungi Screenshot

Dove il corso indica **[Screenshot]**, devi aggiungere immagini reali:

1. **Screenshot Bybit:**
   - Homepage: https://www.bybit.com
   - Testnet: https://testnet.bybit.com
   - API Management: sezione user

2. **Screenshot VS Code:**
   - Apri VS Code sul tuo PC
   - Installa le estensioni menzionate
   - Fai screenshot

3. **Screenshot Terminal:**
   - Apri terminale
   - Esegui comandi docker
   - Cattura l'output

4. **Screenshot Dashboard:**
   - Avvia il sistema in locale
   - Apri http://localhost:8080
   - Cattura la dashboard

### Come Fare Screenshot:
- **Windows:** Win + Shift + S
- **Mac:** Cmd + Shift + 4
- **Linux:** Screenshot tool o `gnome-screenshot`

## 🎥 Passo 7: Aggiungi Animazioni

GAMMA permette animazioni base:

1. Clicca su un elemento
2. Seleziona "Animate"
3. Scegli:
   - **Fade In** per testo normale
   - **Slide In** per blocchi di codice
   - **Highlight** per punti importanti

## 📤 Passo 8: Esporta o Pubblica

### Opzione A: Presenta Online
- Clicca "Present"
- Condividi il link

### Opzione B: Esporta PDF
- Clicca "Export"
- Seleziona "PDF"
- Scarica

### Opzione C: Esporta PowerPoint
- Clicca "Export"
- Seleziona "PPTX"
- Apri in PowerPoint/Google Slides per ulteriori modifiche

## 💡 Tips e Trucchi

### Per Risultati Migliori:

1. **Usa Markdown Corretto**
   - I titoli `#` diventano titoli slide
   - I sottotitoli `##` diventano sezioni
   - Il testo normale diventa contenuto

2. **Blocchi di Codice**
   - Usa sempre triple backticks \`\`\`
   - Specifica il linguaggio: \`\`\`python

3. **Tabelle**
   - GAMMA legge le tabelle markdown
   - Usa `|` per separare colonne

4. **Emoji**
   - Le emoji funzionano! 🚀
   - Usale per rendere le slide più vivaci

### Risoluzione Problemi:

- **Slide troppo lunghe?** Dividi il testo in più sezioni
- **Formattazione sbagliata?** Usa l'editor manuale di GAMMA
- **Immagini non caricate?** Controlla il formato (PNG/JPG)
- **Tema non piace?** Puoi cambiarlo dopo nelle impostazioni

## 📊 Struttura Finale Consigliata

```
📁 Corso Trading Bot AI (GAMMA)
├── 📄 Modulo 0 - Introduzione (4 slide)
├── 📄 Modulo 1 - AI e LLM (6 slide)
├── 📄 Modulo 2 - Trading Crypto (7 slide)
├── 📄 Modulo 3 - Ambiente Dev (7 slide)
├── 📄 Modulo 4 - Docker Server (7 slide)
├── 📄 Modulo 5 - I 9 Agenti (10 slide)
├── 📄 Modulo 6 - Config e Test (6 slide)
├── 📄 Modulo 7 - Dashboard (4 slide)
├── 📄 Modulo 8 - Strategie (7 slide)
├── 📄 Bonus - Esempi LLM (4 slide)
└── 📄 Conclusione (4 slide)
```

## ✅ Checklist Finale

Prima di pubblicare il corso:

- [ ] Tutte le slide hanno contenuto
- [ ] I blocchi di codice sono leggibili
- [ ] Gli screenshot sono stati aggiunti
- [ ] I link sono cliccabili
- [ ] Il tema è coerente
- [ ] Le animazioni funzionano
- [ ] Ho fatto una preview completa
- [ ] Ho salvato/esportato una copia

---

**Buon lavoro! 🎯**
