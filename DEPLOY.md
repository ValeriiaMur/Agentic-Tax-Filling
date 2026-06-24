# Deploy runbook — Railway

**Live deployment: <https://agentic-tax-filling.up.railway.app/>** (health:
`/healthz`).

The app is a single FastAPI service. Railway builds it from `requirements.txt`
and starts it with the command in `railway.json`. Target: a public URL a judge
can open.

## One-time deploy

1. **Push the latest code** (from this repo root):

   ```bash
   git add -A && git commit -m "deploy" && git push origin main
   ```

2. **Create the Railway project**
   - Go to <https://railway.app> → **New Project** → **Deploy from GitHub repo**.
   - Select `ValeriiaMur/Agentic-Tax-Filling` and confirm.
   - Railway auto-detects Python and uses `railway.json`'s start command:
     `uvicorn app.server:app --host 0.0.0.0 --port $PORT`.

3. **(Optional) Enable W-2 image vision**
   - Project → **Variables** → add `ANTHROPIC_API_KEY = sk-ant-...`.
   - Without it, the **Use sample W-2** and **Use blurry phone photo** buttons
     still work end-to-end (figures come from the backend fixture); only
     uploading an arbitrary photo needs the key.
   - To also warm the agent's phrasing with Claude, add `USE_LLM_PHRASING = 1`.

4. **Get the URL**
   - Project → **Settings** → **Networking** → **Generate Domain**.
   - You'll get something like `https://agentic-tax-filling-production.up.railway.app`.

## Smoke test the live URL

Replace `$URL` with your domain:

```bash
curl -s $URL/healthz                       # -> {"ok":true,...}
open $URL                                  # idle screen → Begin → Use sample W-2
```

In the browser: **Begin → Use sample W-2 → Confirm → answer the 5 questions →
Looks right → Download return**. Open the **Decision trail** pill (top-right) to
see the observation log. The download is the real filled IRS Form 1040 PDF.

## Redeploy

Every `git push origin main` triggers an automatic redeploy. To roll back, redeploy
a previous commit from the Railway **Deployments** tab.

## Same setup on Render / Fly.io

The `Procfile` (`web: uvicorn app.server:app --host 0.0.0.0 --port $PORT`) works on
any host that injects `$PORT`. On Render: **New Web Service → Build:
`pip install -r requirements.txt` → Start: the Procfile command**.
