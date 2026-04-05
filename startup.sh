#!/bin/bash

# Azure App Service startup script for IT Helpdesk Assistant
# Starts both the MCP server (background) and Streamlit UI (foreground)

set -e

echo "🚀 IT Helpdesk Assistant - Starting up..."
echo "Environment: $ENVIRONMENT"
echo "App Domain: ithelpdesk-pod2-demo.azurewebsites.net"

# Create necessary directories
mkdir -p /tmp/streamlit
mkdir -p /tmp/mcp

# Keep MCP internal-only inside the App Service container.
export MCP_BIND_HOST=127.0.0.1
export MCP_PORT=8000
export MCP_SERVER_URL=http://127.0.0.1:8000/mcp

# Start MCP Server in background
echo "📡 Starting MCP Server on port 8000 (background)..."
python mcp_server.py --http &
MCP_PID=$!
echo "MCP Server PID: $MCP_PID"

# Cleanup background MCP process when container stops.
trap "kill $MCP_PID 2>/dev/null || true" EXIT

# Wait for MCP server to be ready
echo "⏳ Waiting for MCP Server to initialize..."
for i in {1..30}; do
  if curl -s -o /dev/null http://127.0.0.1:8000/mcp; then
    echo "✅ MCP Server is ready"
    break
  fi
  echo "  Attempt $i/30 - waiting..."
  sleep 1
done

# Start Streamlit UI on Azure-assigned public app port
echo "🎨 Starting Streamlit UI..."
echo "Streamlit will run on port: ${PORT:-8000}"

# Set Streamlit config for app service
export STREAMLIT_SERVER_PORT=${PORT:-8000}
export STREAMLIT_SERVER_HEADLESS=true
export STREAMLIT_SERVER_ENABLEXSRFPROTECTION=false
export STREAMLIT_SERVER_ENABLECORS=false
export STREAMLIT_LOGGER_LEVEL=info

# Run Streamlit in foreground (blocking)
streamlit run app_ui.py \
  --server.port=${PORT:-8000} \
  --server.address=0.0.0.0 \
  --server.headless=true
