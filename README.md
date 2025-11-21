# Trading Agent System - Mobile Edition

A multi-user AI-powered cryptocurrency trading bot system with mobile app support. Each user can register, connect their exchange API keys, and run their own personalized trading bot.

## 🌟 Features

### Multi-User Support
- User registration and authentication
- Secure API key storage with encryption
- Per-user bot configurations
- User isolation for trading operations

### Mobile App
- 📱 React Native mobile application
- 🔐 Secure login and registration
- 🔑 Exchange API key management
- 🤖 Start/stop trading bot
- ⚙️ Configure trading parameters
- 📊 Real-time bot status monitoring

### Trading System
- Multiple AI agents for technical analysis
- Fibonacci and Gann analysis
- News sentiment analysis
- Master AI brain for decision making
- Position management
- Support for multiple exchanges (Bybit, Binance, etc.)

## 🏗️ Architecture

The system consists of:

1. **Backend Services**
   - Authentication Service (FastAPI) - User management and API key storage
   - Multiple AI Agent Services - Technical analysis, Fibonacci, Gann, News Sentiment
   - Orchestrator - Coordinates trading decisions per user
   - PostgreSQL Database - User data and configurations

2. **Mobile App**
   - React Native with Expo
   - Cross-platform (iOS/Android)
   - User-friendly interface

## 🚀 Quick Start

### Prerequisites

- Docker and Docker Compose
- Node.js 16+ (for mobile app development)
- Expo CLI (for mobile app)

### Backend Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd trading-agent-system
```

2. Create a `.env` file with your configuration:
```bash
# JWT and Encryption
JWT_SECRET_KEY=your-secure-random-key-here
ENCRYPTION_KEY=your-fernet-encryption-key-here

# Exchange API Keys (optional, users will provide their own)
BYBIT_API_KEY=your-key
BYBIT_API_SECRET=your-secret

# Other services
OPENAI_API_KEY=your-openai-key
CRYPTOPANIC_API_KEY=your-cryptopanic-key
```

3. Start all services:
```bash
docker-compose up -d
```

4. Verify services are running:
```bash
docker-compose ps
```

The authentication service will be available at `http://localhost:8001`

### Mobile App Setup

1. Navigate to mobile app directory:
```bash
cd mobile-app
```

2. Install dependencies:
```bash
npm install
```

3. Update API URL in `src/services/api.js`:
```javascript
const API_URL = 'http://YOUR_IP:8001'; // Replace with your server IP
```

4. Start the app:
```bash
npm start
```

5. Open with Expo Go on your phone or press `i` for iOS simulator / `a` for Android emulator

## 📱 Using the Mobile App

1. **Register**: Create a new account
2. **Login**: Sign in with your credentials
3. **Add Exchange Keys**: Navigate to "Manage API Keys" and add your exchange credentials
4. **Configure Bot**: Go to Settings to configure trading pairs, leverage, and position size
5. **Start Trading**: Toggle the bot on from the home screen

## 🔒 Security

- All API keys are encrypted using Fernet symmetric encryption
- JWT tokens for secure authentication
- Password hashing with bcrypt
- User data isolation
- HTTPS recommended for production

## 🛠️ Configuration

### Bot Parameters (per user)

- **Trading Pairs**: Select which cryptocurrencies to trade
- **Position Size**: Amount in USDT per trade
- **Leverage**: Leverage multiplier (1-20x)
- **Bot Status**: Enable/disable trading

### Supported Exchanges

- Bybit (default)
- Binance (configurable)
- More exchanges can be added

## 📊 API Endpoints

### Authentication Service (Port 8001)

- `POST /register` - Register new user
- `POST /login` - User login
- `GET /me` - Get current user info
- `POST /exchange-keys` - Add/update exchange keys
- `GET /exchange-keys` - List user's exchange keys
- `DELETE /exchange-keys/{id}` - Remove exchange key
- `GET /bot-config` - Get bot configuration
- `PUT /bot-config` - Update bot configuration

### Agent Services

- Technical Analyzer (Port 8002)
- Fibonacci Agent (Port 8003)
- Master AI Agent (Port 8004)
- Gann Analyzer (Port 8005)
- News Sentiment (Port 8006)
- Position Manager (Port 8007)

## 🔧 Development

### Backend Development

Each service can be developed independently:

```bash
# Run a specific service
cd backend/auth_service
pip install -r requirements.txt
python main.py
```

### Mobile App Development

```bash
cd mobile-app
npm start
```

For hot reloading and faster development, use Expo's developer tools.

## 📦 Deployment

### Backend

1. Update environment variables for production
2. Use HTTPS for all endpoints
3. Configure proper database backups
4. Set strong JWT and encryption keys

```bash
docker-compose up -d --build
```

### Mobile App

Build production apps:

```bash
# iOS
expo build:ios

# Android
expo build:android
```

Then publish to App Store and Google Play.

## 🐛 Troubleshooting

### Cannot connect to backend from mobile

- Ensure backend is accessible from your device
- Use your computer's IP address, not `localhost`
- Check firewall settings
- Verify backend is running: `curl http://localhost:8001`

### Database issues

```bash
# Reset database
docker-compose down -v
docker-compose up -d
```

### Mobile app issues

```bash
# Clear cache
expo start -c

# Reinstall dependencies
rm -rf node_modules
npm install
```

## 📝 License

MIT

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📧 Support

For issues and questions, please open an issue on GitHub.
