# Architecture Overview

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                           MOBILE APP LAYER                          │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │            React Native Mobile Application                     │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐         │  │
│  │  │  Login/  │ │   Home   │ │   API    │ │  Config  │         │  │
│  │  │ Register │ │Dashboard │ │   Keys   │ │ Settings │         │  │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘         │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  │ HTTPS/REST API
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      AUTHENTICATION SERVICE                         │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │              FastAPI Authentication Server                     │  │
│  │  • User Registration & Login (JWT)                            │  │
│  │  • Encrypted API Key Storage (Fernet)                         │  │
│  │  • Bot Configuration Management                               │  │
│  │  • Multi-tenant User Isolation                                │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                         ┌────────┴────────┐
                         │                 │
                         ▼                 ▼
┌──────────────────────────────┐  ┌────────────────────────────────┐
│     PostgreSQL Database      │  │   Multi-User Orchestrator      │
│  • Users Table               │  │  • Fetch Active Users          │
│  • Exchange Keys (Encrypted) │  │  • Create User Sessions        │
│  • Bot Configurations        │  │  • Execute Trading Cycles      │
└──────────────────────────────┘  │  • Per-User Isolation          │
                                  └────────────────────────────────┘
                                              │
                      ┌───────────────────────┼───────────────────────┐
                      │                       │                       │
                      ▼                       ▼                       ▼
        ┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐
        │ Technical Analyzer  │  │  Fibonacci Agent    │  │   Gann Analyzer     │
        │     Agent (AI)      │  │       (AI)          │  │      (AI)           │
        │  • Multi-TF Analysis│  │  • Support/Res      │  │  • Time Cycles      │
        │  • RSI, MACD, etc.  │  │  • Fibonacci Levels │  │  • Square of 9      │
        └─────────────────────┘  └─────────────────────┘  └─────────────────────┘
                      │                       │                       │
                      └───────────────────────┼───────────────────────┘
                                              │
                                              ▼
                                  ┌─────────────────────┐
                                  │  Master AI Brain    │
                                  │     (GPT-4)         │
                                  │  • Decision Making  │
                                  │  • Risk Management  │
                                  │  • Trade Setup      │
                                  └─────────────────────┘
                                              │
                      ┌───────────────────────┼───────────────────────┐
                      │                       │                       │
                      ▼                       ▼                       ▼
        ┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐
        │  News Sentiment     │  │ Position Manager    │  │  Exchange API       │
        │     Agent (AI)      │  │      Agent          │  │  (Bybit/Binance)    │
        │  • News Analysis    │  │  • Active Positions │  │  • Order Execution  │
        │  • Market Sentiment │  │  • Risk Management  │  │  • Balance Check    │
        └─────────────────────┘  └─────────────────────┘  └─────────────────────┘
```

## Data Flow

### 1. User Registration & Login

```
Mobile App → Auth Service → PostgreSQL
    ↓
  JWT Token
    ↓
Mobile App (stores token)
```

### 2. API Key Configuration

```
Mobile App → Auth Service → Encrypt Keys → PostgreSQL
                                               ↓
                                         Encrypted Storage
```

### 3. Trading Cycle (Per User)

```
Orchestrator → Auth Service → Get Active Users
                ↓
            User Session Created
                ↓
    ┌───────────┴───────────┐
    │                       │
    ▼                       ▼
Get API Keys          Get Bot Config
    │                       │
    └───────────┬───────────┘
                ▼
        For Each Symbol:
                │
    ┌───────────┴───────────┐
    │   Gather AI Insights  │
    ├───────────────────────┤
    │ • Technical Analysis  │
    │ • Fibonacci Levels    │
    │ • Gann Analysis       │
    │ • News Sentiment      │
    └───────────┬───────────┘
                ▼
        Master AI Brain
                ↓
         Decision Made
                ↓
        ┌───────┴────────┐
        │                │
    WAIT/HOLD      OPEN_LONG/SHORT
                        ↓
                Execute Trade
                        ↓
                Exchange API
```

## Security Layers

### 1. Authentication Layer
- JWT tokens with expiration
- Bcrypt password hashing
- Token refresh mechanism

### 2. Encryption Layer
- Fernet symmetric encryption for API keys
- Unique encryption key per deployment
- Secure key storage

### 3. Network Layer
- HTTPS for all communications
- CORS configuration
- API rate limiting (recommended)

### 4. Database Layer
- User data isolation
- Encrypted sensitive data
- Regular backups

## Scaling Considerations

### Horizontal Scaling

```
                    Load Balancer
                          │
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼
   Auth Service      Auth Service      Auth Service
   (Instance 1)      (Instance 2)      (Instance 3)
        │                 │                 │
        └─────────────────┼─────────────────┘
                          │
                    PostgreSQL
                    (with replicas)
```

### Vertical Scaling

- Increase resources for AI agents
- More CPU for decision-making
- More memory for data analysis

### Database Scaling

- Read replicas for queries
- Write master for updates
- Connection pooling
- Caching layer (Redis)

## Deployment Architectures

### Development (Docker Compose)

All services on single machine:
```
docker-compose up
```

### Production (Kubernetes)

```
┌─────────────────────────────────────────┐
│           Kubernetes Cluster            │
│  ┌─────────────────────────────────┐    │
│  │  Ingress Controller (HTTPS)     │    │
│  └────────────┬────────────────────┘    │
│               │                         │
│     ┌─────────┴─────────┐              │
│     ▼                   ▼              │
│  ┌─────┐            ┌─────┐            │
│  │ Pod │            │ Pod │            │
│  │Auth │            │Agent│            │
│  └─────┘            └─────┘            │
│                                         │
│  ┌─────────────────────────────────┐   │
│  │  PostgreSQL StatefulSet         │   │
│  └─────────────────────────────────┘   │
└─────────────────────────────────────────┘
```

### Cloud (AWS/GCP/Azure)

```
┌─────────────────────────────────────────┐
│              Load Balancer              │
│              (HTTPS/TLS)                │
└─────────────┬───────────────────────────┘
              │
    ┌─────────┴─────────┐
    ▼                   ▼
┌─────────┐       ┌─────────┐
│  ECS/   │       │  RDS    │
│  EKS    │       │ (DB)    │
│Services │       └─────────┘
└─────────┘
```

## Technology Stack

### Backend
- **Language**: Python 3.11+
- **API Framework**: FastAPI
- **Database**: PostgreSQL 15
- **ORM**: SQLAlchemy
- **Authentication**: JWT (PyJWT)
- **Encryption**: Cryptography (Fernet)
- **Exchange**: CCXT, Pybit

### AI/ML
- **AI Brain**: OpenAI GPT-4
- **Analysis**: Custom algorithms
- **Libraries**: NumPy, Pandas, SciPy

### Mobile
- **Framework**: React Native
- **Build Tool**: Expo
- **State**: React Context API
- **Navigation**: React Navigation
- **UI**: React Native Paper
- **HTTP Client**: Axios

### DevOps
- **Containerization**: Docker
- **Orchestration**: Docker Compose / Kubernetes
- **CI/CD**: GitHub Actions (recommended)
- **Monitoring**: Prometheus + Grafana (recommended)

## API Endpoints Summary

### Authentication Service (Port 8001)

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/` | Health check | No |
| POST | `/register` | Register new user | No |
| POST | `/login` | User login | No |
| GET | `/me` | Get current user | Yes |
| POST | `/exchange-keys` | Add/update API key | Yes |
| GET | `/exchange-keys` | List user's keys | Yes |
| DELETE | `/exchange-keys/{id}` | Delete API key | Yes |
| GET | `/bot-config` | Get bot config | Yes |
| PUT | `/bot-config` | Update bot config | Yes |
| GET | `/active-users` | Get active users (internal) | No |

### Agent Services

| Service | Port | Description |
|---------|------|-------------|
| Technical Analyzer | 8002 | Multi-timeframe analysis |
| Fibonacci Agent | 8003 | Support/resistance levels |
| Master AI Brain | 8004 | Decision making |
| Gann Analyzer | 8005 | Time cycle analysis |
| News Sentiment | 8006 | Market sentiment |
| Position Manager | 8007 | Active position management |

## Performance Considerations

### Response Times (Target)
- Authentication: < 100ms
- API Key Operations: < 200ms
- Trading Decision: < 5s (depends on AI)
- Order Execution: < 1s

### Throughput
- Auth Service: 100+ req/s
- AI Agents: 10-20 decisions/s
- Database: 1000+ queries/s

### Resource Usage
- Auth Service: 512MB RAM, 0.5 CPU
- AI Agents: 1GB RAM, 1 CPU each
- Database: 2GB RAM, 1 CPU
- Orchestrator: 512MB RAM, 0.5 CPU

## Future Enhancements

### Planned Features
- [ ] Real-time WebSocket notifications
- [ ] Advanced portfolio analytics
- [ ] Backtesting engine
- [ ] Strategy marketplace
- [ ] Social trading features
- [ ] Multi-exchange support
- [ ] Advanced risk management
- [ ] Machine learning models
- [ ] Performance dashboards
- [ ] Mobile push notifications

### Infrastructure
- [ ] Kubernetes deployment
- [ ] Redis caching layer
- [ ] Message queue (RabbitMQ/Kafka)
- [ ] Monitoring & alerting
- [ ] Automated backups
- [ ] Disaster recovery
- [ ] CDN for static assets
- [ ] Rate limiting
- [ ] DDoS protection

## Support & Maintenance

### Monitoring
- Service health checks
- Database performance
- API response times
- Error rates
- User activity

### Logging
- Structured logging (JSON)
- Centralized log aggregation
- Error tracking
- Audit logs

### Backup Strategy
- Daily database backups
- Weekly full backups
- Point-in-time recovery
- Off-site backup storage

## Conclusion

This architecture provides:
- ✅ Scalability for multiple users
- ✅ Security for sensitive data
- ✅ Isolation between users
- ✅ Easy deployment
- ✅ Mobile-first design
- ✅ Extensibility for new features

For questions or contributions, please open an issue on GitHub.
