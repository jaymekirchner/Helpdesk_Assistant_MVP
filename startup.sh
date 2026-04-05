#!/bin/bash

# Azure App Service startup script for IT Helpdesk Assistant
# Starts both the MCP server (background) and Streamlit UI (foreground)

set -euo pipefail

echo "🚀 IT Helpdesk Assistant - Starting up..."
echo "Environment: ${ENVIRONMENT:-unknown}"
echo "App Domain: ithelpdesk-pod2-demo.azurewebsites.net"

# Create necessary directories
mkdir -p /tmp/streamlit
mkdir -p /tmp/mcp

# Keep MCP internal-only inside the App Service container.
export MCP_BIND_HOST=127.0.0.1
export MCP_PORT=8000
export MCP_SERVER_URL=http://127.0.0.1:8000/mcp

# Start MCP server in background without blocking app warmup.
echo "📡 Starting MCP Server on port 8000 (background)..."
python mcp_server.py --http > /tmp/mcp/server.log 2>&1 &
MCP_PID=$!
echo "MCP Server PID: $MCP_PID"

# Cleanup background MCP process when container stops.
trap "kill $MCP_PID 2>/dev/null || true" EXIT

# Start Streamlit UI on Azure-assigned public app port
echo "🎨 Starting Streamlit UI..."
echo "Streamlit will run on port: ${PORT:-8000}"

# Set Streamlit config for app service
export STREAMLIT_SERVER_PORT=${PORT:-8000}
export STREAMLIT_SERVER_HEADLESS=true
export STREAMLIT_SERVER_ENABLEXSRFPROTECTION=false
export STREAMLIT_SERVER_ENABLECORS=false
export STREAMLIT_LOGGER_LEVEL=info

# Run Streamlit in foreground as PID 1 so App Service health checks succeed.
exec python -m streamlit run app_ui.py \
  --server.port=${PORT:-8000} \
  --server.address=0.0.0.0 \
  --server.headless=true
