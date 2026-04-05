# 📦 Azure App Service Deployment Package

**Application:** IT Helpdesk Assistant MVP  
**Target Domain:** `ithelpdesk-pod2-demo.azurewebsites.net`  
**Status:** ✅ Ready for Deployment  
**Created:** 2026-04-04  

---

## 📋 Package Contents

### Core Application Files
```
✅ app_ui.py                    # Streamlit frontend UI
✅ appFinal.py                  # MAF agents & business logic
✅ mcp_server.py                # MCP tool server (UPDATED: env vars)
✅ tool_data.py                 # Mock data & utilities
✅ requirements.txt             # Python dependencies (UPDATED)
```

### Deployment Configuration Files (NEW)
```
✅ startup.sh                   # Azure App Service startup script
✅ web.config                   # IIS reverse proxy configuration
✅ .env.example                 # Configuration template
✅ .gitignore                   # Git ignore rules (UPDATED)
✅ local-start.sh               # Local testing startup script
```

### Documentation Files (NEW)
```
✅ DEPLOYMENT_GUIDE.md          # Complete deployment instructions
✅ PACKAGE_SUMMARY.md           # This file
```

---

## 🔧 What Was Fixed/Updated

### 1. **Database Connection String** (mcp_server.py)
- ❌ **Before:** Hardcoded connection string
- ✅ **After:** Uses environment variables with fallback
  ```python
  def _postgres_conn_string() -> str:
      conn_str = os.getenv("POSTGRES_CONNECTION_STRING", "")
      # Also supports individual component env vars
  ```

### 2. **Requirements.txt**
Added version pinning and compatibility:
- `psycopg2-binary` (instead of just `psycopg2`)
- `gunicorn` for production WSGI server
- Version constraints for stability

### 3. **Configuration Management**
- Created `.env.example` template
- All secrets now configurable via environment variables
- Ready for Azure Key Vault integration

---

## 🚀 Quick Start for Azure Deployment

### Prerequisite
- Azure subscription
- Resource Group created
- App Service created (Python 3.10 runtime)

### 3-Step Deployment

**1. Set Configuration in Azure Portal:**
```
App Service → Configuration → Application Settings
Add all variables from .env.example
```

**2. Deploy Code:**
```bash
# Option A: Git push (if Git deployment is configured)
git push azure main

# Option B: ZIP deployment
zip -r deployment.zip . -x ".venv/*" ".git/*" "__pycache__/*" "*.pyc" ".env"
az webapp deployment source config-zip \
  -g ai-bootcamp-openai-pod2 \
  -n ithelpdesk-pod2-demo \
  --src deployment.zip
```

**3. Set Startup Command:**
```bash
# In Azure Portal: App Service → Configuration → Startup Command
bash /home/site/wwwroot/startup.sh
```

---

## 🧪 Local Testing Before Deployment

### Test Locally
```bash
# Make scripts executable
chmod +x startup.sh local-start.sh

# Run local test (builds venv, installs deps, starts both services)
./local-start.sh
```

**Expected Output:**
```
✅ MCP Server is ready on http://localhost:8000
🎨 Starting Streamlit UI on port 8501
📍 Web UI: http://localhost:8501
```

### Validate Local Setup
```bash
# In another terminal, test MCP health
curl http://localhost:8000

# Test Streamlit UI
Open browser: http://localhost:8501
```

---

## 📊 Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Azure App Service (ithelpdesk-pod2-demo.azurewebsites.net) │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Port 8501: Streamlit Web UI (app_ui.py)                  │
│  ├─ Chat interface                                         │
│  ├─ Message history                                        │
│  └─ Real-time health checks                               │
│                                                             │
│  ↓ (calls)                                                 │
│                                                             │
│  Business Logic (appFinal.py)                              │
│  ├─ Triage Agent (classify issues)                         │
│  ├─ Knowledge Agent (provide help)                         │
│  ├─ Action Agent (perform tasks)                           │
│  └─ RAG with Azure Search                                  │
│                                                             │
│  ↓ (calls)                                                 │
│                                                             │
│  Port 8000: MCP Tool Server (mcp_server.py --http)        │
│  ├─ health_check                                           │
│  ├─ lookup_user (PostgreSQL)                               │
│  ├─ check_device_status (PostgreSQL)                       │
│  └─ create_ticket (Freshworks API)                         │
│                                                             │
└─────────────────────────────────────────────────────────────┘
         ↓ External Services
    ┌────────────────────────────────┐
    │ Azure Resources                │
    ├────────────────────────────────┤
    │ • Cognitive Search (RAG)       │
    │ • OpenAI (GPT-4o-mini)         │
    │ • PostgreSQL (user/device DB)  │
    │ • Freshworks (ticketing)       │
    └────────────────────────────────┘
```

---

## 🔐 Security Checklist

- [ ] All secrets in Application Settings (not in code)
- [ ] `.env` file in `.gitignore` (don't commit)
- [ ] HTTPS Only enabled on App Service
- [ ] Web sockets enabled
- [ ] PostgreSQL firewall allows App Service IP
- [ ] Managed Identity configured (if using Key Vault)
- [ ] Network Security Group rules configured

---

## 📝 Environment Variables Required

**Core Azure Services:**
```
AZURE_OPENAI_ENDPOINT          # Your OpenAI resource
AZURE_OPENAI_API_KEY           # OpenAI API key
AZURE_OPENAI_DEPLOYMENT        # Model deployment name
AZURE_SEARCH_ENDPOINT          # Cognitive Search endpoint
AZURE_SEARCH_KEY               # Search API key
AZURE_SEARCH_INDEX             # Index name
```

**Database:**
```
POSTGRES_CONNECTION_STRING     # Full connection string (recommended)
  OR
POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_HOST, POSTGRES_PORT
```

**Ticketing (Optional):**
```
FRESHWORKS_API_KEY             # Freshworks API key
FRESHWORKS_DOMAIN              # Freshworks domain
FRESHWORKS_DEFAULT_REQUESTER_EMAIL
```

**Streamlit UI:**
```
STREAMLIT_SERVER_PORT=8501
STREAMLIT_SERVER_HEADLESS=true
STREAMLIT_SERVER_ENABLEXSRFPROTECTION=false
```

---

## 🐛 Troubleshooting

### "ModuleNotFoundError: No module named..."
- **Cause:** Missing dependencies
- **Fix:** Ensure all packages in `requirements.txt` installed
  ```bash
  pip install -r requirements.txt
  ```

### "MCP Server not reachable"
- **Cause:** Port 8000 not accessible or server crashed
- **Fix:** Check logs:
  ```bash
  az webapp log tail -n ithelpdesk-pod2-demo -g ai-bootcamp-openai-pod2
  ```

### "psycopg2 ImportError"
- **Cause:** Using `psycopg2` instead of `psycopg2-binary`
- **Fix:** Already fixed in `requirements.txt`

### Slow startup in Azure
- **Cause:** First-time Python compilation or large dependencies
- **Fix:** 
  - Increase App Service tier to B2 or S1
  - Pre-warm with keep-alive requests

---

## 📈 Performance & Cost

### Recommended Azure SKUs
| Environment | App Service Plan | Estimated Cost |
|---|---|---|
| Dev/Test | B2 | ~$0.15/hour |
| Small Production | S1 | ~$0.10/hour |
| Medium Production | S2 | ~$0.20/hour |

### Cost Optimization Tips
1. Use B-series for non-critical deployments
2. Enable auto-shutdown for dev environments
3. Use Azure SQL (serverless) for variable workloads
4. Cache results where possible

---

## ✅ Deployment Verification Checklist

After deployment, verify:

- [ ] App Service shows "Running" status
- [ ] Application Settings all configured
- [ ] Health endpoint responds: `curl https://ithelpdesk-pod2-demo.azurewebsites.net/api/health`
- [ ] Streamlit UI loads: `https://ithelpdesk-pod2-demo.azurewebsites.net`
- [ ] Can send chat messages
- [ ] MCP tools work (lookup user, check device, create ticket)
- [ ] No errors in Application Logs
- [ ] Database connectivity working
- [ ] Azure Search queries working

---

## 📚 Next Steps

1. **Deploy to Azure:**
   - Follow DEPLOYMENT_GUIDE.md step-by-step

2. **Monitor in Production:**
   - Set up Application Insights
   - Configure alerts

3. **Optimize Performance:**
   - Monitor response times
   - Adjust tier if needed
   - Cache frequently accessed queries

4. **Continuous Improvement:**
   - Set up CI/CD pipeline (GitHub Actions)
   - Auto-deploy on commits to main branch

---

## 📞 Support

For issues:
1. Check Application Logs in Azure Portal
2. Review DEPLOYMENT_GUIDE.md troubleshooting section
3. Test locally with `./local-start.sh`
4. Enable Application Insights for detailed diagnostics

---

**Package Status:** ✅ Ready for Production Deployment  
**Last Updated:** 2026-04-04  
**Maintainer:** GitHub Copilot
