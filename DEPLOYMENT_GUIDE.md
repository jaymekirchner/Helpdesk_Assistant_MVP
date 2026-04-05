# Azure App Service Deployment Guide

## IT Helpdesk Assistant MVP
**Target Domain:** `ithelpdesk-pod2-demo.azurewebsites.net`

---

## 📋 Pre-Deployment Checklist

### 1. Azure Resources Required
- [ ] Azure App Service (Python 3.10 runtime)
- [ ] Azure Cognitive Search instance
- [ ] Azure OpenAI resource
- [ ] PostgreSQL database (Azure Database for PostgreSQL)
- [ ] Freshworks API access (optional, for ticketing)

### 2. Configuration & Credentials
- [ ] Azure OpenAI endpoint & API key
- [ ] Azure Search endpoint & API key
- [ ] PostgreSQL connection string
- [ ] Freshworks API key (if using ticketing)

---

## 🚀 Deployment Steps

### Step 1: Prepare the Environment

Linux App Service note:
- Startup is configured in Azure Portal under Configuration > General settings > Startup Command.
- If the field is not visible in your portal view, set it with Azure CLI using `az webapp config set --startup-file`.

1. **Set up Application Settings in App Service:**
   - In Azure Portal: App Service → Configuration → Application settings
   - Add all variables from `.env.example`:

   ```
   AZURE_OPENAI_ENDPOINT=https://ai-bootcamp-openai-pod2.openai.azure.com/
   AZURE_OPENAI_API_KEY=<your-key>
   AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini
   AZURE_OPENAI_API_VERSION=2024-02-15-preview
   
   AZURE_SEARCH_ENDPOINT=https://ai-bootcamp-search-pod2.search.windows.net
   AZURE_SEARCH_KEY=<your-key>
   AZURE_SEARCH_INDEX=rag-1774655785839
   
   POSTGRES_CONNECTION_STRING=dbname=postgres user=ithelpdesk_pod2_admin password=<your-password> host=ithelpdesk-pod2-postgres-db.postgres.database.azure.com port=5432
   
   FRESHWORKS_API_KEY=<your-key>
   FRESHWORKS_DOMAIN=<your-domain>
   
   STREAMLIT_SERVER_PORT=8000
   STREAMLIT_SERVER_HEADLESS=true
   MCP_BIND_HOST=127.0.0.1
   MCP_PORT=8000
   MCP_SERVER_URL=http://127.0.0.1:8000/mcp
   ```

2. **Enable Web Sockets:**
   - App Service → Configuration → General settings → Web sockets → ON

3. **Set Startup Command (Linux plans only):**
   - App Service → Configuration → Startup Command:
   ```bash
   bash /home/site/wwwroot/startup.sh
   ```

### Step 2: Deploy Code

**Option A: Git Deployment (Recommended)**

```bash
# Clone or navigate to your repo
cd /path/to/Helpdesk_Assistant_MVP

# Add Azure remote
az webapp deployment source config-zip -g <resource-group> -n ithelpdesk-pod2-demo --src deployment.zip

# Or use Git:
git remote add azure https://<deployment-user>@ithelpdesk-pod2-demo.scm.azurewebsites.net/ithelpdesk-pod2-demo.git
git push azure main
```

**Option B: ZIP Deployment**

```bash
# Create deployment package
zip -r deployment.zip . -x "\.venv/*" "\.git/*" "__pycache__/*" "*.pyc" ".env" "dist/*"

# Deploy
az webapp deployment source config-zip \
  --resource-group <your-resource-group> \
  --name ithelpdesk-pod2-demo \
  --src deployment.zip
```

### Step 3: Install Dependencies

App Service automatically runs: `pip install -r requirements.txt` if using Python buildpack.

**Manual install (if needed):**
```bash
# SSH into App Service
ssh <app-service-name>.azurewebsites.net

# Navigate to app directory
cd /home/site/wwwroot

# Install requirements
pip install -r requirements.txt
```

### Step 4: Verify Deployment

1. **Check MCP Server Health:**
   ```bash
   curl https://ithelpdesk-pod2-demo.azurewebsites.net/api/health
   ```
   Expected response:
   ```json
   {
     "success": true,
     "error": null,
     "data": {
       "status": "ready",
       "checks": {
         "postgres": "ok",
         "freshworks": "configured"
       }
     }
   }
   ```

2. **Access Streamlit UI:**
   Navigate to: `https://ithelpdesk-pod2-demo.azurewebsites.net`

3. **Check Application Logs:**
   - Azure Portal → App Service → Logs → Log stream
   - Or SSH and check:
     ```bash
     tail -f /home/site/wwwroot/python.log
     ```

---

## 🔧 Architecture Overview

```
┌─────────────────────────────────────────────────┐
│  Azure App Service (Web App)                    │
│  ithelpdesk-pod2-demo.azurewebsites.net        │
├─────────────────────────────────────────────────┤
│                                                 │
│  ┌──────────────────────────────────────────┐  │
│  │  Streamlit Frontend (Port = $PORT)       │  │
│  │  - app_ui.py                             │  │
│  │  - Handles chat UI & conversations       │  │
│  └──────────────────────────────────────────┘  │
│           ↓ (calls)                            │
│  ┌──────────────────────────────────────────┐  │
│  │  AppFinal.py (Business Logic)            │  │
│  │  - MAF Agents (Triage, Knowledge, Action)│  │
│  │  - RAG with Azure Search                 │  │
│  │  - Orchestration                         │  │
│  └──────────────────────────────────────────┘  │
│           ↓ (calls)                            │
│  ┌──────────────────────────────────────────┐  │
│  │  MCP Server (Port 8000)                  │  │
│  │  - mcp_server.py (HTTP transport)        │  │
│  │  - Tools: health_check, lookup_user,     │  │
│  │    check_device_status, create_ticket    │  │
│  └──────────────────────────────────────────┘  │
│                                                 │
└────────────┬────────────────────────────────────┘
             ↓ (calls)
     External Services:
     - Azure Cognitive Search
     - Azure OpenAI
     - PostgreSQL Database
     - Freshworks API
```

---

## 📝 File Structure for Deployment

```
ithelpdesk-pod2-demo/
├── app_ui.py                 # Streamlit frontend
├── appFinal.py               # Business logic & MAF agents
├── mcp_server.py             # MCP tool server
├── tool_data.py              # Mock data
├── requirements.txt          # Python dependencies (updated)
├── startup.sh                # Startup script (NEW)
├── DEPLOYMENT_GUIDE.md       # This file
├── Readme.md                 # Original README
├── tickets.jsonl             # Ticket storage
├── infra/                    # Infrastructure (Bicep, etc.)
└── documentation/            # Project documentation
```

---

## 🔍 Troubleshooting

### Issue: "MCP Server not reachable"

**Solution:**
1. Verify `POSTGRES_CONNECTION_STRING` is set correctly
2. Check PostgreSQL firewall rules allow App Service IP
3. See Application Logs:
   ```bash
   az webapp log tail -n ithelpdesk-pod2-demo -g <resource-group>
   ```

### Issue: Streamlit times out loading

**Solution:**
1. Increase App Service plan tier (Standard or Premium)
2. Check Azure Search connection in Logs
3. Verify `STREAMLIT_SERVER_TIMEOUT` is sufficient

### Issue: "Tools not found" in Streamlit

**Solution:**
1. Ensure MCP server is running: `curl http://localhost:8000/health`
2. Check `startup.sh` executed successfully
3. Verify port 8000 is accessible from Streamlit container

### Issue: Database connection failures

**Solution:**
1. Test connection locally:
   ```bash
   psql "postgres://user:password@host:5432/postgres"
   ```
2. Azure Portal → PostgreSQL Database → Connection Security → Firewall rules
3. Add App Service's outbound IP address

---

## 📊 Performance & Scaling

### Recommended Tier
- **Development:** B2 (1 vCPU, 1.75 GB RAM)
- **Production:** S2 (2 vCPU, 3.5 GB RAM) with Always On enabled

### Enable Always On
- Azure Portal → App Service → Settings → Always On → ON
- Prevents app from unloading during idle periods

### Scaling
```bash
# Auto-scale based on CPU
az appservice plan update --name <plan-name> \
  --resource-group <group> \
  --sku P1V2
```

---

## 🔐 Security Best Practices

1. **Never commit `.env` file** — use Application Settings
2. **Enable HTTPS only:**
   - App Service → Configuration → HTTPS Only → ON

3. **Restrict IP access (optional):**
   - App Service → Networking → Access Restrictions

4. **Enable Managed Identity:**
   - App Service → Identity → System assigned → ON
   - Use for Azure Key Vault access

5. **Monitor for threats:**
   - Azure Portal → Security Center
   - Check for suspicious activity logs

---

## ✅ Post-Deployment Validation

```bash
# Test health endpoint
curl https://ithelpdesk-pod2-demo.azurewebsites.net/api/health

# Test chat endpoint (if web_app.py is added)
curl -X POST https://ithelpdesk-pod2-demo.azurewebsites.net/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "test"}'

# Check application logs
az webapp log tail -n ithelpdesk-pod2-demo -g <resource-group>
```

---

## 📞 Support & Next Steps

1. **Enable Application Insights** for monitoring:
   ```bash
   az webapp config appsettings set -n ithelpdesk-pod2-demo \
     -g <resource-group> \
     --settings APPINSIGHTS_INSTRUMENTATIONKEY=<key>
   ```

2. **Set up CI/CD pipeline** (GitHub Actions):
   - Azure Portal → Deployment Center → GitHub
   - Auto-deploy on push to `main` branch

3. **Monitor with Log Analytics:**
   - Connect to Application Insights for detailed telemetry

---

**Last Updated:** 2026-04-04  
**Version:** 1.0  
**Status:** Production Ready
