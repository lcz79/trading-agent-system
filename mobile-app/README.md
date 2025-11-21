# Trading Bot Mobile App

A React Native mobile application for managing your AI-powered cryptocurrency trading bot.

## Features

- 🔐 User authentication (register/login)
- 🔑 Secure API key management for exchanges
- 🤖 Start/stop trading bot
- ⚙️ Configure trading parameters (symbols, leverage, position size)
- 📊 Monitor bot status
- 👤 User profile management

## Tech Stack

- React Native with Expo
- React Navigation
- React Native Paper (UI components)
- AsyncStorage for local storage
- Axios for API calls

## Prerequisites

- Node.js 16 or higher
- npm or yarn
- Expo CLI (`npm install -g expo-cli`)
- iOS Simulator (for iOS development) or Android Studio (for Android development)

## Installation

1. Navigate to the mobile-app directory:
```bash
cd mobile-app
```

2. Install dependencies:
```bash
npm install
```

3. Update the API URL in `src/services/api.js`:
```javascript
const API_URL = 'http://YOUR_BACKEND_IP:8001';
```

## Running the App

### Development

Start the Expo development server:
```bash
npm start
```

Then:
- Press `i` to open iOS simulator
- Press `a` to open Android emulator
- Scan the QR code with Expo Go app on your phone

### Specific Platforms

```bash
# iOS
npm run ios

# Android
npm run android

# Web (for testing)
npm run web
```

## Building for Production

### iOS

```bash
expo build:ios
```

### Android

```bash
expo build:android
```

## Configuration

The app connects to the backend authentication service. Make sure the backend is running and accessible from your device.

### Environment Variables

You can configure the API URL in the `app.json` file:

```json
{
  "expo": {
    "extra": {
      "apiUrl": "http://YOUR_BACKEND_IP:8001"
    }
  }
}
```

## Screens

1. **Login/Register**: User authentication
2. **Home**: Dashboard showing bot status and quick actions
3. **Exchange Keys**: Manage exchange API keys
4. **Settings**: Configure bot parameters
5. **Profile**: User information and logout

## Security

- All API keys are encrypted before being stored in the database
- JWT tokens are used for authentication
- Tokens are stored securely in AsyncStorage
- All API communication uses HTTPS in production

## Troubleshooting

### Cannot connect to backend

- Ensure the backend is running
- Check the API URL in `src/services/api.js`
- If using a physical device, ensure it's on the same network as your backend
- Use your computer's IP address instead of `localhost`

### Expo issues

```bash
# Clear cache
expo start -c

# Reset project
rm -rf node_modules
npm install
```

## License

MIT
