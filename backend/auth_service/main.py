import os
import secrets
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from passlib.context import CryptContext
import jwt
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from cryptography.fernet import Fernet

# --- Configuration ---
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://trading_user:trading_pass@postgres:5432/trading_db")
SECRET_KEY = os.getenv("JWT_SECRET_KEY", secrets.token_urlsafe(32))
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
INTERNAL_SERVICE_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN", secrets.token_urlsafe(32))
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

# --- Database Setup ---
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- Security ---
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()
cipher_suite = Fernet(ENCRYPTION_KEY.encode())

# --- Models ---
class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Integer, default=1)

class ExchangeKey(Base):
    __tablename__ = "exchange_keys"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    exchange_name = Column(String, nullable=False)  # e.g., "bybit", "binance"
    encrypted_api_key = Column(Text, nullable=False)
    encrypted_api_secret = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Integer, default=1)

class BotConfig(Base):
    __tablename__ = "bot_configs"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    is_running = Column(Integer, default=0)
    symbols = Column(Text)  # JSON string of symbols
    qty_usdt = Column(Integer, default=50)
    leverage = Column(Integer, default=5)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# Create tables
Base.metadata.create_all(bind=engine)

# --- Pydantic Schemas ---
class UserRegister(BaseModel):
    email: EmailStr
    username: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class UserResponse(BaseModel):
    id: int
    email: str
    username: str
    created_at: datetime

class ExchangeKeyCreate(BaseModel):
    exchange_name: str
    api_key: str
    api_secret: str

class ExchangeKeyResponse(BaseModel):
    id: int
    exchange_name: str
    created_at: datetime

class BotConfigUpdate(BaseModel):
    is_running: Optional[bool] = None
    symbols: Optional[List[str]] = None
    qty_usdt: Optional[int] = None
    leverage: Optional[int] = None

class BotConfigResponse(BaseModel):
    id: int
    is_running: bool
    symbols: List[str]
    qty_usdt: int
    leverage: int

# --- FastAPI App ---
app = FastAPI(title="Trading Bot Auth Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Helper Functions ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def encrypt_data(data: str) -> str:
    return cipher_suite.encrypt(data.encode()).decode()

def decrypt_data(encrypted_data: str) -> str:
    return cipher_suite.decrypt(encrypted_data.encode()).decode()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    try:
        token = credentials.credentials
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid authentication credentials")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.JWTError:
        raise HTTPException(status_code=401, detail="Could not validate credentials")
    
    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user

async def verify_internal_token(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """Verify internal service token for service-to-service communication"""
    token = credentials.credentials
    if token != INTERNAL_SERVICE_TOKEN:
        raise HTTPException(
            status_code=401, 
            detail="Invalid internal service token"
        )
    return True

# --- API Endpoints ---
@app.get("/")
async def root():
    return {"message": "Trading Bot Auth Service", "version": "1.0.0"}

@app.post("/register", response_model=UserResponse)
async def register(user_data: UserRegister, db: Session = Depends(get_db)):
    # Check if user exists
    existing_user = db.query(User).filter(
        (User.email == user_data.email) | (User.username == user_data.username)
    ).first()
    
    if existing_user:
        raise HTTPException(status_code=400, detail="User already exists")
    
    # Create new user
    hashed_password = get_password_hash(user_data.password)
    new_user = User(
        email=user_data.email,
        username=user_data.username,
        hashed_password=hashed_password
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return new_user

@app.post("/login", response_model=Token)
async def login(user_data: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == user_data.username).first()
    
    if not user or not verify_password(user_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )
    
    if not user.is_active:
        raise HTTPException(status_code=400, detail="User account is inactive")
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.id}, expires_delta=access_token_expires
    )
    
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user

@app.post("/exchange-keys", response_model=ExchangeKeyResponse)
async def add_exchange_key(
    key_data: ExchangeKeyCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Encrypt API keys
    encrypted_key = encrypt_data(key_data.api_key)
    encrypted_secret = encrypt_data(key_data.api_secret)
    
    # Check if user already has key for this exchange
    existing_key = db.query(ExchangeKey).filter(
        ExchangeKey.user_id == current_user.id,
        ExchangeKey.exchange_name == key_data.exchange_name,
        ExchangeKey.is_active == 1
    ).first()
    
    if existing_key:
        # Update existing key
        existing_key.encrypted_api_key = encrypted_key
        existing_key.encrypted_api_secret = encrypted_secret
        db.commit()
        db.refresh(existing_key)
        return existing_key
    
    # Create new key
    new_key = ExchangeKey(
        user_id=current_user.id,
        exchange_name=key_data.exchange_name,
        encrypted_api_key=encrypted_key,
        encrypted_api_secret=encrypted_secret
    )
    
    db.add(new_key)
    db.commit()
    db.refresh(new_key)
    
    return new_key

@app.get("/exchange-keys", response_model=List[ExchangeKeyResponse])
async def get_exchange_keys(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    keys = db.query(ExchangeKey).filter(
        ExchangeKey.user_id == current_user.id,
        ExchangeKey.is_active == 1
    ).all()
    return keys

@app.delete("/exchange-keys/{key_id}")
async def delete_exchange_key(
    key_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    key = db.query(ExchangeKey).filter(
        ExchangeKey.id == key_id,
        ExchangeKey.user_id == current_user.id
    ).first()
    
    if not key:
        raise HTTPException(status_code=404, detail="Key not found")
    
    key.is_active = 0
    db.commit()
    
    return {"message": "Key deleted successfully"}

@app.get("/bot-config", response_model=BotConfigResponse)
async def get_bot_config(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    config = db.query(BotConfig).filter(BotConfig.user_id == current_user.id).first()
    
    if not config:
        # Create default config
        import json
        config = BotConfig(
            user_id=current_user.id,
            symbols=json.dumps(["BTCUSDT", "ETHUSDT", "SOLUSDT"])
        )
        db.add(config)
        db.commit()
        db.refresh(config)
    
    import json
    return {
        "id": config.id,
        "is_running": bool(config.is_running),
        "symbols": json.loads(config.symbols) if config.symbols else [],
        "qty_usdt": config.qty_usdt,
        "leverage": config.leverage
    }

@app.put("/bot-config", response_model=BotConfigResponse)
async def update_bot_config(
    config_data: BotConfigUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    import json
    
    config = db.query(BotConfig).filter(BotConfig.user_id == current_user.id).first()
    
    if not config:
        config = BotConfig(user_id=current_user.id)
        db.add(config)
    
    if config_data.is_running is not None:
        config.is_running = 1 if config_data.is_running else 0
    if config_data.symbols is not None:
        config.symbols = json.dumps(config_data.symbols)
    if config_data.qty_usdt is not None:
        config.qty_usdt = config_data.qty_usdt
    if config_data.leverage is not None:
        config.leverage = config_data.leverage
    
    config.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(config)
    
    return {
        "id": config.id,
        "is_running": bool(config.is_running),
        "symbols": json.loads(config.symbols) if config.symbols else [],
        "qty_usdt": config.qty_usdt,
        "leverage": config.leverage
    }

@app.get("/exchange-keys/{exchange_name}/decrypt")
async def get_decrypted_keys(
    exchange_name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Internal endpoint for services to get decrypted keys"""
    key = db.query(ExchangeKey).filter(
        ExchangeKey.user_id == current_user.id,
        ExchangeKey.exchange_name == exchange_name,
        ExchangeKey.is_active == 1
    ).first()
    
    if not key:
        raise HTTPException(status_code=404, detail="Exchange keys not found")
    
    return {
        "api_key": decrypt_data(key.encrypted_api_key),
        "api_secret": decrypt_data(key.encrypted_api_secret)
    }

@app.get("/active-users")
async def get_active_users(
    verified: bool = Depends(verify_internal_token),
    db: Session = Depends(get_db)
):
    """Get all users with running bots (internal endpoint for orchestrator)"""
    # Get all bot configs that are running
    active_configs = db.query(BotConfig).filter(BotConfig.is_running == 1).all()
    
    result = []
    for config in active_configs:
        # Get user info
        user = db.query(User).filter(User.id == config.user_id, User.is_active == 1).first()
        if not user:
            continue
        
        # Get exchange keys
        exchange_keys = db.query(ExchangeKey).filter(
            ExchangeKey.user_id == config.user_id,
            ExchangeKey.is_active == 1
        ).all()
        
        if not exchange_keys:
            continue
        
        # Use first available exchange
        exchange = exchange_keys[0]
        
        result.append({
            "user_id": user.id,
            "username": user.username,
            "exchange": exchange.exchange_name,
            "config": {
                "symbols": config.symbols,
                "qty_usdt": config.qty_usdt,
                "leverage": config.leverage
            }
        })
    
    return result

@app.get("/users/{user_id}/exchange-keys/{exchange_name}/decrypt")
async def get_user_decrypted_keys(
    user_id: int,
    exchange_name: str,
    verified: bool = Depends(verify_internal_token),
    db: Session = Depends(get_db)
):
    """Internal endpoint for orchestrator to get user's decrypted keys"""
    key = db.query(ExchangeKey).filter(
        ExchangeKey.user_id == user_id,
        ExchangeKey.exchange_name == exchange_name,
        ExchangeKey.is_active == 1
    ).first()
    
    if not key:
        raise HTTPException(status_code=404, detail="Exchange keys not found")
    
    return {
        "api_key": decrypt_data(key.encrypted_api_key),
        "api_secret": decrypt_data(key.encrypted_api_secret)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
