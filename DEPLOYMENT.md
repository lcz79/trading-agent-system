# Mobile App Deployment Guide

## Overview

This guide covers deploying the Trading Bot mobile application for both iOS and Android platforms.

## Prerequisites

### For iOS
- macOS computer with Xcode installed
- Apple Developer Account ($99/year)
- iOS device for testing

### For Android
- Android Studio installed
- Google Play Developer Account ($25 one-time)
- Android device for testing

### For Both
- Node.js 16+ installed
- Expo CLI installed (`npm install -g expo-cli`)
- EAS CLI installed (`npm install -g eas-cli`)

## Development Testing

### 1. Test on Physical Device (Recommended)

This is the easiest way to test the app on a real device:

```bash
cd mobile-app
npm install
npm start
```

Then:
- Install "Expo Go" app on your phone from App Store/Google Play
- Scan the QR code displayed in your terminal
- The app will load on your device

**Important**: Your phone and computer must be on the same network.

### 2. Configure API URL

Before testing, update the API URL in `src/services/api.js`:

```javascript
// Replace localhost with your computer's IP address
const API_URL = 'http://192.168.1.100:8001'; // Your IP here
```

To find your IP:
- **macOS/Linux**: `ifconfig | grep "inet "` or `ip addr show`
- **Windows**: `ipconfig`

## Production Deployment

### Option 1: Expo Go (Easiest, but limited)

Users can access your app through Expo Go without publishing to stores:

```bash
cd mobile-app
expo publish
```

Users then:
1. Install Expo Go
2. Scan your published project's QR code
3. App runs in Expo Go

**Limitations**: 
- Requires Expo Go app
- Not a standalone app
- Less professional

### Option 2: Standalone Apps (Recommended)

Build standalone apps for App Store and Google Play:

#### Setup EAS Build

1. Create an Expo account at https://expo.dev
2. Login:
```bash
eas login
```

3. Configure your project:
```bash
cd mobile-app
eas build:configure
```

#### Build for Android

1. Create a build:
```bash
eas build -p android --profile production
```

2. Download the APK/AAB from Expo dashboard
3. Upload to Google Play Console

**For Google Play**:
- First build will take ~20-30 minutes
- Creates a signed APK/AAB file
- Upload to Google Play Console for review
- Review process takes 1-7 days

#### Build for iOS

1. Create a build:
```bash
eas build -p ios --profile production
```

2. Download the IPA from Expo dashboard
3. Upload to App Store Connect using Transporter app

**For App Store**:
- Need Apple Developer Account
- First build takes ~30-45 minutes
- Creates signed IPA file
- Upload to App Store Connect for review
- Review process takes 1-3 days

### Option 3: OTA Updates

After publishing to stores, update your app without resubmitting:

```bash
eas update --branch production --message "Bug fixes"
```

Users get updates automatically when they open the app.

## Configuration for Production

### 1. Update app.json

```json
{
  "expo": {
    "name": "Trading Bot",
    "slug": "trading-bot-mobile",
    "version": "1.0.0",
    "icon": "./assets/icon.png",
    "extra": {
      "apiUrl": "https://your-production-api.com"
    }
  }
}
```

### 2. Update API URL

In `src/services/api.js`, use the production URL:

```javascript
import Constants from 'expo-constants';

const API_URL = Constants.expoConfig.extra.apiUrl || 'http://localhost:8001';
```

### 3. Add App Icons and Splash Screen

Replace placeholder images in `assets/`:
- `icon.png` - 1024x1024px app icon
- `splash.png` - Splash screen image
- `adaptive-icon.png` - Android adaptive icon (1024x1024px)

Use tools like:
- https://www.appicon.co/
- https://makeappicon.com/

### 4. Configure App Identifiers

Update in `app.json`:

```json
{
  "ios": {
    "bundleIdentifier": "com.yourcompany.tradingbot"
  },
  "android": {
    "package": "com.yourcompany.tradingbot"
  }
}
```

## Store Submission

### Google Play Store

1. Create app in Google Play Console
2. Fill out store listing:
   - App name, description, screenshots
   - Privacy policy URL (required)
   - Content rating questionnaire
3. Upload APK/AAB file
4. Submit for review

**Required Screenshots**:
- At least 2 screenshots
- 1080x1920px or 1080x2340px
- Show main features

### Apple App Store

1. Create app in App Store Connect
2. Fill out app information:
   - Name, subtitle, description
   - Keywords (100 characters max)
   - Screenshots for all device sizes
   - Privacy policy URL (required)
3. Upload IPA using Transporter
4. Submit for review

**Required Screenshots**:
- 6.5" iPhone (1284x2778px)
- 5.5" iPhone (1242x2208px)
- iPad Pro (2048x2732px)

### Privacy Policy

You need a privacy policy. Include:
- Data collection (email, API keys)
- Data usage (trading, authentication)
- Data storage and security
- Third-party services (if any)

Host it on your website or use free services like:
- https://www.freeprivacypolicy.com/
- https://app-privacy-policy-generator.firebaseapp.com/

## Testing Before Release

### 1. TestFlight (iOS)

Share with beta testers:
```bash
eas build -p ios --profile preview
```

Add testers in App Store Connect → TestFlight.

### 2. Internal Testing (Android)

Upload to Internal Testing track in Google Play Console.
Share link with testers.

## Post-Deployment

### Monitor App Performance

- Check crash reports in App Store Connect / Google Play Console
- Monitor user reviews
- Track downloads and engagement

### Update Process

1. Make changes to code
2. Update version in `app.json`
3. For minor updates:
   ```bash
   eas update
   ```
4. For major updates:
   ```bash
   eas build -p all --profile production
   ```
5. Submit to stores

## Troubleshooting

### Build Fails

```bash
# Clear cache
expo start -c

# Update packages
npm update

# Check EAS build logs
eas build:list
```

### App Rejected

Common reasons:
- Missing privacy policy
- Incomplete app information
- Crash on launch
- Violates store policies

Fix issues and resubmit.

### Can't Connect to Backend

- Verify API URL is correct
- Use HTTPS in production
- Check CORS settings on backend
- Test API endpoints with Postman

## Security Checklist

Before deploying:

- [ ] Use HTTPS for API
- [ ] Hide sensitive keys (use environment variables)
- [ ] Enable SSL certificate pinning (advanced)
- [ ] Implement proper error handling
- [ ] Test on multiple devices
- [ ] Review privacy policy
- [ ] Secure API endpoints
- [ ] Test authentication flow
- [ ] Verify data encryption

## Resources

- Expo Documentation: https://docs.expo.dev/
- EAS Build: https://docs.expo.dev/build/introduction/
- App Store Guidelines: https://developer.apple.com/app-store/review/guidelines/
- Play Store Guidelines: https://play.google.com/console/about/guides/
- React Native Paper: https://callstack.github.io/react-native-paper/

## Support

For issues:
1. Check Expo forums
2. Review GitHub issues
3. Consult React Native community
4. Contact support

## Cost Breakdown

- Apple Developer: $99/year
- Google Play: $25 one-time
- Expo (free tier is fine for small apps)
- EAS Build: Check current pricing at expo.dev
- SSL Certificate: Free with Let's Encrypt
- Backend hosting: Varies by provider

## Next Steps

After deployment:
1. Monitor user feedback
2. Fix bugs quickly
3. Plan new features
4. Regular updates
5. Marketing and promotion

Good luck with your deployment! 🚀
