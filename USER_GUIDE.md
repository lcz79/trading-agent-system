# Mobile App User Guide

## Getting Started

### 1. Installation

#### For Development/Testing
1. Install Expo Go on your phone:
   - iOS: Download from App Store
   - Android: Download from Google Play

2. Get the app running:
   ```bash
   cd mobile-app
   npm install
   npm start
   ```

3. Scan the QR code with Expo Go

#### For Production
Download from:
- iOS: App Store (search "Trading Bot")
- Android: Google Play (search "Trading Bot")

## App Screens Guide

### 🔐 Login Screen

**First Time Users:**
1. Tap "Don't have an account? Register"
2. Go to Registration

**Existing Users:**
1. Enter your username
2. Enter your password
3. Tap "Login"

**Features:**
- Secure authentication
- Password hidden by default
- Error messages for invalid credentials

---

### 📝 Registration Screen

**Steps:**
1. Enter your email address
2. Choose a username
3. Create a password (minimum 6 characters)
4. Confirm your password
5. Tap "Register"

**Requirements:**
- Valid email format
- Unique username
- Password at least 6 characters
- Passwords must match

**After Registration:**
- Automatically logged in
- Redirected to Home screen

---

### 🏠 Home Screen (Dashboard)

**What You See:**
- Welcome message with your username
- Bot status (Running/Stopped)
- Quick toggle to start/stop bot
- Current configuration summary
- Quick access buttons

**Bot Status Card:**
- 🟢 Green = Bot is running
- 🔴 Red = Bot is stopped
- Toggle switch to start/stop

**Configuration Summary:**
- Trading pairs currently active
- Position size per trade
- Leverage setting

**Quick Actions:**
- "Configure Bot" → Settings screen
- "Manage API Keys" → Exchange Keys screen

**Pull to Refresh:**
- Swipe down to reload data
- Updates bot status and config

---

### 🔑 Exchange Keys Screen

**Purpose:**
Connect your exchange account to enable trading

**Adding API Keys:**
1. Tap "Add API Key" button
2. Enter exchange name (e.g., "bybit")
3. Paste your API Key
4. Paste your API Secret
5. Tap "Add Key"

**Important:**
- Keys are encrypted before storage
- Never shared with third parties
- Only you can access your keys
- Can be deleted at any time

**Managing Keys:**
- View all connected exchanges
- See when each key was added
- Delete keys you no longer need

**Getting API Keys:**

**For Bybit:**
1. Log into Bybit.com
2. Go to API Management
3. Create new API key
4. Enable "Trade" permissions
5. Copy API Key and Secret

**For Binance:**
1. Log into Binance.com
2. Go to API Management
3. Create new API key
4. Enable "Spot & Margin Trading"
5. Copy API Key and Secret

---

### ⚙️ Settings Screen (Bot Configuration)

**Trading Parameters:**

**Position Size:**
- Amount in USDT per trade
- Example: 50 = $50 per trade
- Minimum: $10
- Recommended: $50-$500

**Leverage:**
- Multiplier for your position
- Range: 1x to 20x
- Higher = More risk, more reward
- Recommended: 5x or less for beginners

**Trading Pairs:**
- Select cryptocurrencies to trade
- Available options:
  - BTC (Bitcoin)
  - ETH (Ethereum)
  - SOL (Solana)
  - BNB (Binance Coin)
  - XRP (Ripple)
  - ADA (Cardano)
  - DOGE (Dogecoin)
  - AVAX (Avalanche)
  - LINK (Chainlink)
  - MATIC (Polygon)

**Tap to Select:**
- Blue = Selected
- Gray = Not selected
- Select multiple pairs

**Saving Changes:**
1. Configure all settings
2. Tap "Save Configuration"
3. Changes applied immediately
4. Return to home screen

---

### 👤 Profile Screen

**Your Information:**
- Username
- Email address
- Account creation date

**Account Actions:**
- Logout button

**About Section:**
- App version
- Developer information

---

## Common Tasks

### How to Start Trading

1. **Add Exchange Keys** (First Time Only)
   - Go to Home → "Manage API Keys"
   - Add your exchange credentials
   - Keys are encrypted and secure

2. **Configure Bot Settings**
   - Go to Home → "Configure Bot"
   - Set position size (e.g., $50)
   - Set leverage (e.g., 5x)
   - Select trading pairs (e.g., BTC, ETH)
   - Save configuration

3. **Start the Bot**
   - Go to Home screen
   - Toggle "Enable Trading Bot" to ON
   - Bot status changes to 🟢 Running
   - Bot starts analyzing markets

4. **Monitor Activity**
   - Check home screen regularly
   - Pull to refresh for updates
   - View bot status

### How to Stop Trading

1. Go to Home screen
2. Toggle "Enable Trading Bot" to OFF
3. Bot stops immediately
4. Existing positions remain open

### How to Change Settings

1. Stop the bot (recommended)
2. Go to Settings
3. Update your preferences
4. Save changes
5. Restart the bot

### How to Switch Exchanges

1. Stop the bot
2. Go to Exchange Keys
3. Delete old key (optional)
4. Add new exchange key
5. Update settings if needed
6. Restart the bot

## Safety Tips

### 🔒 Security
- Never share your API keys
- Use strong, unique passwords
- Enable 2FA on exchange accounts
- Only use API keys with trading permissions
- Never enable withdrawal permissions

### 💰 Risk Management
- Start with small position sizes
- Use lower leverage initially
- Don't trade more than you can afford to lose
- Diversify across multiple pairs
- Monitor regularly

### 📊 Best Practices
- Check bot status daily
- Review trading performance weekly
- Adjust settings based on market conditions
- Keep exchange account funded
- Maintain internet connection

## Troubleshooting

### Bot Won't Start

**Possible Issues:**
1. No API keys configured
   - Solution: Add exchange keys

2. Invalid API keys
   - Solution: Check and re-enter keys

3. Insufficient balance
   - Solution: Add funds to exchange

4. Network connection issue
   - Solution: Check internet connection

### Can't Connect to Backend

**Solutions:**
1. Check internet connection
2. Verify backend is running
3. Check API URL in settings
4. Contact support if persistent

### API Key Errors

**Solutions:**
1. Verify keys are correct
2. Check exchange API permissions
3. Ensure API key is not expired
4. Try deleting and re-adding key

### Bot Not Trading

**Check:**
1. Bot is enabled (🟢 Running)
2. API keys are valid
3. Exchange account has funds
4. Trading pairs are selected
5. Market conditions meet criteria

## Support

### Getting Help

**Documentation:**
- README.md - Project overview
- SETUP.md - Setup instructions
- ARCHITECTURE.md - Technical details

**Community:**
- GitHub Issues
- Discord (if available)
- Email support

**Reporting Bugs:**
1. Describe the issue
2. Include screenshots
3. Mention device/OS
4. List steps to reproduce

## FAQ

**Q: Is my money safe?**
A: Your funds stay on your exchange account. The bot only executes trades using your API keys.

**Q: How much can I make?**
A: Trading involves risk. Past performance doesn't guarantee future results.

**Q: Can I use multiple exchanges?**
A: Yes, add multiple exchange keys and configure accordingly.

**Q: Does the bot work 24/7?**
A: Yes, as long as the backend service is running.

**Q: Can I modify strategies?**
A: Advanced users can modify the AI agents (backend code).

**Q: What exchanges are supported?**
A: Currently Bybit and Binance. More coming soon.

**Q: Do I need coding skills?**
A: No, the mobile app is user-friendly. Coding only needed for advanced customization.

**Q: Is there a subscription fee?**
A: The app is open source. You only pay exchange trading fees.

**Q: Can I backtest strategies?**
A: Not currently, but it's on the roadmap.

**Q: How do I update the app?**
A: Updates are available through App Store/Google Play.

## Privacy & Data

**What We Collect:**
- Email address (for account)
- Username (for identification)
- API keys (encrypted)
- Bot configurations

**What We Don't Collect:**
- Trading history
- Balance information
- Personal financial data
- Device information (beyond what's needed for app function)

**Data Security:**
- All API keys encrypted
- Passwords hashed with bcrypt
- Secure HTTPS connections
- No data shared with third parties

## Tips for Success

### For Beginners
1. Start with demo/testnet if available
2. Use small position sizes ($10-50)
3. Use low leverage (2-5x)
4. Trade major pairs (BTC, ETH)
5. Monitor daily for first week

### For Advanced Users
1. Customize AI agent parameters
2. Implement custom strategies
3. Add multiple exchanges
4. Use higher position sizes wisely
5. Contribute to the project

## Legal Disclaimer

Trading cryptocurrencies carries risk. This bot:
- Does not guarantee profits
- May result in losses
- Is provided "as is"
- Requires you to accept risk

Always:
- Trade responsibly
- Only risk what you can afford to lose
- Understand the markets
- Comply with local regulations
- Seek professional advice if needed

---

**Version:** 1.0.0  
**Last Updated:** November 2024  
**Support:** GitHub Issues
