# Unleash AI Governance Demo

This demo shows how production teams govern a GPT-5 assistant with Unleash:

- Target internal employees, beta users, and regular users independently.
- Expand GPT-5 traffic gradually while GPT-4 remains the safe fallback.
- Monitor latency, request cost, and hallucination rate.
- Route everyone back to GPT-4 instantly with a kill switch.

The feature flag is `gpt_5_assistant`.

## Architecture

```text
Browser UI -> FastAPI app -> Unleash Python SDK -> Local Unleash server -> Postgres
```

The FastAPI app uses the Unleash Python SDK to evaluate `gpt_5_assistant` with:

```python
client.is_enabled(
    "gpt_5_assistant",
    {"userId": user_id, "properties": {"userType": user_type}},
)
```

Passing `userId` matters because gradual rollouts need a sticky user or session
identifier. That keeps each user on the same experience during a rollout.

## Install

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Start Everything

### 1. Start Unleash and Postgres

```powershell
docker-compose up -d
```

With newer Docker versions, `docker compose up -d` is equivalent.

Unleash UI:

```text
http://localhost:4242
```

The Compose file uses insecure development tokens so the demo is one-command
local setup. Do not use these tokens in production.

Wait until both containers are healthy:

```powershell
docker compose ps
```

### 2. Configure and start the backend

The defaults already target the local Compose server. To set them explicitly:

```powershell
$env:UNLEASH_URL="http://localhost:4242/api"
$env:UNLEASH_API_TOKEN="default:development.unleash-insecure-api-token"
```

```powershell
.venv\Scripts\python.exe -m uvicorn app:app --reload
```

The backend retries while Unleash starts. If it remains unavailable, the app
stays usable with flags safely disabled and displays:

```text
Unleash not connected – running in demo mode
```

It reconnects automatically when Unleash becomes healthy.

### 3. Start the frontend

The frontend is served by FastAPI, so no separate frontend process is needed.
Open:

```text
http://127.0.0.1:8000
```

## Demo Flow

1. Start with GPT-5 disabled and show that every audience receives GPT-4.
2. Enable GPT-5 at 10% to begin the internal and beta canary.
3. Increase rollout above 50% and simulate 50 AI requests.
4. Watch latency, cost, and hallucination metrics trigger an incident.
5. Click **Emergency Kill Switch**.
6. Show that every request immediately returns to GPT-4 and health recovers.

## API

```text
GET  /check?user_id=user-007&user_type=regular
POST /simulate?count=50
POST /update?enabled=true&rollout=50
POST /kill-switch
GET  /logs
GET  /config
GET  /diagnostics
```

## Troubleshooting

If the UI says `Unleash is not reachable yet` or the Admin API message says
`ConnectionError`, the FastAPI app cannot connect to `http://localhost:4242`.

Check:

```powershell
docker compose ps
Invoke-RestMethod http://localhost:4242/health
```

If `/health` does not return successfully, start or restart Unleash:

```powershell
docker compose up -d
```

If Unleash is healthy but all users are still on GPT-4, click **Update Model
Rollout** again. The app creates `gpt_5_assistant`, configures constrained
rollout strategies for each audience, and waits for the SDK cache to refresh.

## Environment Variables

```text
UNLEASH_URL=http://localhost:4242/api
UNLEASH_API_TOKEN=default:development.unleash-insecure-api-token
UNLEASH_ADMIN_TOKEN=*:*.unleash-insecure-admin-api-token
UNLEASH_APP_NAME=ai-governance-demo
UNLEASH_PROJECT_ID=default
UNLEASH_ENVIRONMENT=development
UNLEASH_STARTUP_RETRIES=5
UNLEASH_RETRY_DELAY=0.5
```
