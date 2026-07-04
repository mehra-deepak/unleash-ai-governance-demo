from __future__ import annotations

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from flag_engine import UnleashFeatureFlagGateway


app = FastAPI(
    title="Unleash AI Governance Demo",
    description="A safe GPT-5 rollout demo with audience targeting, governance metrics, and a kill switch.",
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

flags = UnleashFeatureFlagGateway()


@app.on_event("shutdown")
def shutdown_unleash_client() -> None:
    flags.close()


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "config": flags.config(),
        },
    )


@app.get("/check")
def check_assistant(
    user_id: str = Query(..., min_length=1),
    user_type: str = Query("regular", pattern="^(internal|beta|regular)$"),
) -> dict:
    # Unleash selects the model without redeploying the AI application.
    return flags.check(user_id, user_type)


@app.post("/simulate")
def simulate_users(count: int = Query(50, ge=1, le=500)) -> dict:
    return flags.simulate_users(count=count)


@app.get("/config")
def get_config() -> dict:
    return flags.config()


@app.get("/diagnostics")
def get_diagnostics() -> dict:
    return flags.diagnostics()


@app.get("/logs")
def get_logs() -> dict:
    return {"logs": flags.recent_logs()}


@app.post("/update")
def update_release(
    enabled: bool = Query(...),
    rollout: int = Query(..., ge=0, le=100),
) -> dict:
    return flags.update_release(enabled=enabled, rollout=rollout)


@app.post("/kill-switch")
def emergency_kill_switch() -> dict:
    return flags.kill_switch()
