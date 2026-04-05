#!/bin/bash

# Local testing script - mimics Azure App Service startup
# Run this to test the full stack locally before deployment

echo "🧪 IT Helpdesk Assistant - Local Test Startup"
echo "This script simulates the App Service environment"

# Check Python version
python_version=$(python --version 2>&1)
echo "📦 Using: $python_version"

# Check if venv exists
if [ ! -d ".venv" ]; then
    echo "🆕 Creating Python virtual environment..."
    python -m venv .venv
fi

# Activate venv
echo "✅ Activating virtual environment..."
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
    source .venv/Scripts/activate
else
    source .venv/bin/activate
fi

# Install requirements
echo "📥 Installing dependencies..."
pip install -r requirements.txt --quiet

# Check .env file
if [ ! -f ".env" ]; then
    echo "⚠️  .env file not found. Using .env.example as template."
    cp .env.example .env
    echo "📝 Created .env - update it with your credentials"
    echo "   Edit .env and set your Azure credentials before running again"
    exit 1
fi

# Create directories
mkdir -p /tmp/streamlit
mkdir -p /tmp/mcp

# Start MCP Server in background
echo "📡 Starting MCP Server on port 8000..."
python mcp_server.py --http &
MCP_PID=$!
echo "   MCP Server PID: $MCP_PID"

# Wait for MCP server to be ready
echo "⏳ Waiting for MCP Server to initialize (max 30 attempts)..."
for i in {1..30}; do
  if curl -s http://localhost:8000 > /dev/null 2>&1; then
    echo "✅ MCP Server is ready on http://localhost:8000"
    break
  fi
  if [ $i -eq 30 ]; then
    echo "❌ MCP Server failed to start"
    kill $MCP_PID 2>/dev/null || true
    exit 1
  fi
  echo "   Attempt $i/30..."
  sleep 1
done

# Set Streamlit environment
export STREAMLIT_SERVER_PORT=8501
export STREAMLIT_SERVER_HEADLESS=false
export STREAMLIT_CLIENT_THEME_BASE=light

echo ""
echo "🎨 Starting Streamlit UI on port 8501..."
echo "📍 Web UI: http://localhost:8501"
echo "💡 MCP Server: http://localhost:8000"
echo ""
echo "Press Ctrl+C to stop everything"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Run Streamlit in foreground
streamlit run app_ui.py --server.port=8501

# Cleanup on exit
trap "echo 'Shutting down...'; kill $MCP_PID 2>/dev/null || true" EXIT
