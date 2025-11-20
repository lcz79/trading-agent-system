# 🚀 Quick Start - N8N Workflow Import

## ⚡ Fast Import Steps

### Option 1: Import from File (Recommended)
1. Open N8N at `http://localhost:5678`
2. Login with your credentials
3. Click **"+"** (New Workflow)
4. Click **"..."** (three dots, top right)
5. Select **"Import from File"**
6. Choose `n8n_complete_workflow.json`
7. Done! ✅

### Option 2: Copy & Paste
1. Open `n8n_complete_workflow.json` in this repository
2. Copy the **entire content** (Ctrl+A, Ctrl+C)
3. Open N8N at `http://localhost:5678`
4. Login with your credentials
5. Click **"+"** (New Workflow)
6. Click **"..."** (three dots, top right)
7. Select **"Import from URL / Clipboard"**
8. Paste the JSON content
9. Click **"Import"**
10. Done! ✅

## ✅ Pre-Import Checklist

Before importing, make sure:

- [ ] All Docker containers are running:
  ```bash
  docker-compose up -d
  docker-compose ps  # Check all services are "Up"
  ```

- [ ] Environment variables are set:
  - `OPENAI_API_KEY` (for Master AI Agent)
  - `COINGECKO_API_KEY` (for CoinGecko Agent)
  - `EXCHANGE_API_KEY` (for Order Executor)
  - `EXCHANGE_API_SECRET` (for Order Executor)

- [ ] N8N is accessible at `http://localhost:5678`

## ⚙️ Quick Configuration

After import, configure these parameters in the workflow:

### 1. Portfolio Settings
In node **"5. Prepare Data"**, modify:
```javascript
portfolio_state: {
  total_capital_eur: 10000.0,        // Your total capital
  available_capital_eur: 10000.0,    // Available capital
  max_risk_per_trade_percent: 1.0    // Max risk per trade (1%)
}
```

### 2. Trading Symbol (Optional)
Default: `BTCUSDT`

To change, edit in these nodes:
- 1. Technical Analyzer
- 2. Fibonacci Analyzer
- 3. Gann Analyzer
- 4. CoinGecko News
- Prepare Order

### 3. Schedule Intervals (Optional)
- **Every 15 Minutes**: Technical agents
- **Every Hour (CoinGecko)**: News agent

To modify, click on the trigger nodes and adjust the interval.

## 🧪 Test Before Activation

**IMPORTANT:** Always test manually first!

1. Open the imported workflow
2. Click **"Execute Workflow"** (top right)
3. Watch each node execute
4. Check for errors in node outputs
5. Verify data flows correctly

## ✅ Activate the Workflow

Once testing is successful:

1. Toggle **"Active"** switch (top right) to **ON**
2. The workflow will now run automatically:
   - Technical agents: every 15 minutes
   - CoinGecko agent: every hour

## 📊 Monitor Execution

### View Execution History
1. Go to **"Executions"** in the left sidebar
2. Select "Trading Agent System - Complete Workflow"
3. View all past executions, errors, and results

### Check Agent Logs
```bash
# View all logs
docker-compose logs -f

# View specific agent
docker-compose logs -f master-ai-agent
docker-compose logs -f order-executor-agent
```

## 🛟 Quick Troubleshooting

### "Connection refused" errors?
```bash
# Check all containers are running
docker-compose ps

# Restart if needed
docker-compose restart
```

### CoinGecko API errors?
```bash
# Check environment variable is set
docker-compose config | grep COINGECKO_API_KEY
```

### Master AI always returns HOLD?
```bash
# Check OpenAI API key
docker-compose config | grep OPENAI_API_KEY

# Check agent logs
docker-compose logs master-ai-agent
```

## 📚 Full Documentation

For complete documentation, see: **`N8N_WORKFLOW_README.md`**

## ⚠️ Important Notes

1. **Default Mode:** The workflow operates in **mainnet mode** (REAL MONEY!)
2. **Bybit Integration:** Ensure your Bybit API credentials are correctly configured
3. **API Costs:** CoinGecko and OpenAI APIs may incur costs - monitor usage
4. **Risk Management:** Start with small position sizes and monitor constantly
5. **Never commit API keys** to the repository
6. **N8N Compatibility:** This workflow is optimized for n8n v1.45.1 with merge node typeVersion 2.1

## 🎯 What Happens After Activation

1. **Every 15 minutes:**
   - Technical analysis runs
   - Fibonacci analysis runs
   - Gann analysis runs
   - Data merged and sent to Master AI
   - Trading decision made
   - Order executed if BUY/SELL

2. **Every hour (every 4th cycle):**
   - CoinGecko news data refreshed
   - Sentiment analysis updated

## 📞 Need Help?

1. Check the logs: `docker-compose logs -f`
2. Read the full guide: `N8N_WORKFLOW_README.md`
3. Test manually before activating
4. Start with small capital amounts

---

**Ready to start?** Just import the `n8n_complete_workflow.json` file and follow the steps above! 🚀
