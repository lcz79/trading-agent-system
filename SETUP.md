# Setup Guide

## Initial Setup

### 1. Generate Secure Keys

Before starting the application, you need to generate secure keys for JWT and encryption.

#### Generate JWT Secret Key

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

#### Generate Encryption Key

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

#### Generate Internal Service Token

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 2. Configure Environment Variables

1. Copy the example environment file:
```bash
cp .env.example .env
```

2. Edit `.env` and replace the placeholder values:
   - `JWT_SECRET_KEY`: Use the JWT key generated above
   - `ENCRYPTION_KEY`: Use the encryption key generated above
   - `INTERNAL_SERVICE_TOKEN`: Use the internal token generated above
   - Add your exchange API keys (optional, users can add their own)
   - Add your OpenAI API key
   - Add your CryptoPanic API key

### 3. Start the Backend

```bash
docker-compose up -d
```

This will start:
- PostgreSQL database
- Authentication service
- All AI agent services
- Orchestrator

### 4. Verify Services

```bash
# Check all services are running
docker-compose ps

# Check logs
docker-compose logs -f auth-service

# Test auth service
curl http://localhost:8001
```

### 5. Setup Mobile App

1. Navigate to mobile app directory:
```bash
cd mobile-app
```

2. Install dependencies:
```bash
npm install
```

3. Update the API URL:
   - Edit `src/services/api.js`
   - Replace `http://localhost:8001` with your server's IP address
   - If testing on the same machine, use your local IP (not localhost)

4. Start the app:
```bash
npm start
```

### 6. Test the System

1. Open the mobile app on your device or simulator
2. Register a new account
3. Login with your credentials
4. Add your exchange API keys
5. Configure bot settings
6. Start the trading bot

## Development Setup

### Backend Development

Each service can be run independently for development:

```bash
# Auth service
cd backend/auth_service
pip install -r requirements.txt
python main.py

# Agent service
cd agents/04_master_ai_agent
pip install -r requirements.txt
python main.py
```

### Mobile App Development

```bash
cd mobile-app
npm start
```

Use Expo Go app on your phone or iOS/Android simulator.

## Production Deployment

### Backend

1. Update `.env` with production values
2. Use a strong password for PostgreSQL
3. Enable HTTPS for all endpoints
4. Configure firewall rules
5. Set up database backups
6. Use a reverse proxy (nginx/traefik)

```bash
# Start production services
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### Mobile App

1. Update API URL to production endpoint
2. Build for production:

```bash
# iOS
expo build:ios

# Android
expo build:android
```

3. Submit to App Store / Google Play

## Database Management

### Backup Database

```bash
docker exec -t trading-agent-system-postgres-1 pg_dump -U trading_user trading_db > backup.sql
```

### Restore Database

```bash
docker exec -i trading-agent-system-postgres-1 psql -U trading_user trading_db < backup.sql
```

### Reset Database

```bash
docker-compose down -v
docker-compose up -d
```

## Troubleshooting

### Services won't start

```bash
# Check logs
docker-compose logs

# Rebuild services
docker-compose up -d --build
```

### Mobile app can't connect

1. Check backend is running: `docker-compose ps`
2. Verify API URL in `src/services/api.js`
3. Ensure device and server are on same network
4. Check firewall settings
5. Use IP address, not localhost

### Database connection issues

```bash
# Check PostgreSQL is running
docker-compose ps postgres

# Check connection
docker exec -it trading-agent-system-postgres-1 psql -U trading_user -d trading_db
```

## Security Best Practices

1. **Never commit `.env` file** - It contains sensitive keys
2. **Use strong passwords** - For database and user accounts
3. **Enable HTTPS** - In production
4. **Rotate keys regularly** - JWT and encryption keys
5. **Monitor logs** - For suspicious activity
6. **Keep dependencies updated** - Regular security updates
7. **Use network security** - Firewall and VPC
8. **Backup regularly** - Database and configurations

## Support

For issues and questions:
1. Check this guide
2. Review logs: `docker-compose logs`
3. Check GitHub issues
4. Open a new issue with details
