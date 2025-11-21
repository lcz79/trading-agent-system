#!/bin/bash

# Quick Start Script for Trading Agent System
# This script helps you set up the system quickly

set -e

echo "=========================================="
echo "Trading Agent System - Quick Start"
echo "=========================================="
echo ""

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    echo "   Visit: https://docs.docker.com/get-docker/"
    exit 1
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is not installed. Please install Docker Compose first."
    echo "   Visit: https://docs.docker.com/compose/install/"
    exit 1
fi

echo "✅ Docker and Docker Compose are installed"
echo ""

# Check if .env file exists
if [ ! -f .env ]; then
    echo "📝 Creating .env file from template..."
    
    # Generate secure keys
    echo "🔐 Generating secure keys..."
    
    JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))" 2>/dev/null || openssl rand -base64 32)
    ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null || echo "PLEASE_GENERATE_MANUALLY")
    
    # Create .env file
    cat > .env << EOF
# Auto-generated configuration
# Generated on $(date)

# JWT Secret Key
JWT_SECRET_KEY=$JWT_SECRET

# Encryption Key
ENCRYPTION_KEY=$ENCRYPTION_KEY

# Database Configuration
DATABASE_URL=postgresql://trading_user:trading_pass@postgres:5432/trading_db

# Exchange API Keys (optional - users will provide their own via the app)
# BYBIT_API_KEY=your-bybit-api-key
# BYBIT_API_SECRET=your-bybit-api-secret

# AI Services (you need to provide these)
# OPENAI_API_KEY=your-openai-api-key

# News Sentiment (optional)
# CRYPTOPANIC_API_KEY=your-cryptopanic-api-key
EOF
    
    echo "✅ .env file created with secure keys"
    echo ""
    echo "⚠️  IMPORTANT: You need to add your own API keys to .env file:"
    echo "   - OPENAI_API_KEY (required for AI brain)"
    echo "   - CRYPTOPANIC_API_KEY (optional, for news sentiment)"
    echo ""
    echo "   Edit .env file and add these keys before starting."
    echo ""
    read -p "Press Enter to continue or Ctrl+C to exit and edit .env..."
else
    echo "✅ .env file already exists"
    echo ""
fi

# Ask user what to do
echo "What would you like to do?"
echo ""
echo "1) Start all services (backend + database)"
echo "2) Stop all services"
echo "3) View logs"
echo "4) Rebuild and restart services"
echo "5) Run auth service test"
echo "6) Exit"
echo ""
read -p "Enter your choice (1-6): " choice

case $choice in
    1)
        echo ""
        echo "🚀 Starting all services..."
        docker-compose up -d
        echo ""
        echo "✅ Services started!"
        echo ""
        echo "Services are now running:"
        echo "  - PostgreSQL: localhost:5432"
        echo "  - Auth Service: http://localhost:8001"
        echo "  - Technical Analyzer: http://localhost:8002"
        echo "  - Fibonacci Agent: http://localhost:8003"
        echo "  - Master AI: http://localhost:8004"
        echo "  - Gann Analyzer: http://localhost:8005"
        echo "  - News Sentiment: http://localhost:8006"
        echo "  - Position Manager: http://localhost:8007"
        echo ""
        echo "Check status with: docker-compose ps"
        echo "View logs with: docker-compose logs -f"
        echo ""
        echo "⏳ Waiting for services to be ready (30 seconds)..."
        sleep 30
        echo ""
        echo "🧪 Testing auth service..."
        python3 test_auth.py 2>/dev/null || echo "⚠️  Install requests package to run tests: pip3 install requests"
        ;;
    2)
        echo ""
        echo "🛑 Stopping all services..."
        docker-compose down
        echo "✅ Services stopped!"
        ;;
    3)
        echo ""
        echo "📋 Showing logs (Ctrl+C to exit)..."
        docker-compose logs -f
        ;;
    4)
        echo ""
        echo "🔨 Rebuilding and restarting services..."
        docker-compose down
        docker-compose up -d --build
        echo "✅ Services rebuilt and restarted!"
        ;;
    5)
        echo ""
        echo "🧪 Running auth service test..."
        echo ""
        if command -v python3 &> /dev/null; then
            python3 test_auth.py
        else
            echo "❌ Python 3 is not installed"
        fi
        ;;
    6)
        echo "👋 Goodbye!"
        exit 0
        ;;
    *)
        echo "❌ Invalid choice"
        exit 1
        ;;
esac

echo ""
echo "=========================================="
echo "Next steps:"
echo "=========================================="
echo ""
echo "1. Backend is running. Test it:"
echo "   curl http://localhost:8001"
echo ""
echo "2. Set up the mobile app:"
echo "   cd mobile-app"
echo "   npm install"
echo "   npm start"
echo ""
echo "3. Read the documentation:"
echo "   - README.md - Project overview"
echo "   - SETUP.md - Detailed setup guide"
echo "   - DEPLOYMENT.md - Mobile app deployment"
echo ""
echo "4. For help, check the logs:"
echo "   docker-compose logs -f [service-name]"
echo ""
echo "=========================================="
