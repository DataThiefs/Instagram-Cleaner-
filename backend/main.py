import asyncio
import socket
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.ig_service import InstagramAuthError, InstagramRateLimitError, InstagramService
from backend.job_manager import JobManager
from backend.models import (
    AllCleanRequest,
    AuthStatusResponse,
    DeleteStoriesRequest,
    DeleteThreadsRequest,
    JobStatusResponse,
    LoginCredentialsRequest,
    LoginSessionRequest,
    MessageMatchItem,
    SearchMessagesRequest,
    StoryArchiveItem,
    ThreadItem,
    UnsendMessagesRequest,
    WhitelistRequest,
)

ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT_DIR / "frontend"

app = FastAPI(title="InsCleaner API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

ig_service = InstagramService()
job_manager = JobManager(ig_service)


def get_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


# ------------------------------------------------------------------
# System / Network Info
# ------------------------------------------------------------------
@app.get("/api/network")
def network_info() -> dict:
    lan_ip = get_lan_ip()
    return {
        "lan_ip": lan_ip,
        "mobile_url": f"http://{lan_ip}:8000",
        "local_url": "http://127.0.0.1:8000",
    }


# ------------------------------------------------------------------
# Auth Routes
# ------------------------------------------------------------------
@app.get("/api/auth/status", response_model=AuthStatusResponse)
def auth_status() -> AuthStatusResponse:
    return ig_service.get_status()


@app.post("/api/auth/session", response_model=AuthStatusResponse)
async def auth_session(req: LoginSessionRequest) -> AuthStatusResponse:
    try:
        return await asyncio.to_thread(ig_service.login_by_sessionid, req.sessionid)
    except InstagramAuthError as exc:
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": str(exc)}) from exc


@app.post("/api/auth/login", response_model=AuthStatusResponse)
async def auth_login(req: LoginCredentialsRequest) -> AuthStatusResponse:
    try:
        return await asyncio.to_thread(
            ig_service.login_by_credentials,
            req.username,
            req.password,
            req.verification_code,
        )
    except InstagramAuthError as exc:
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": str(exc)}) from exc


@app.post("/api/auth/demo", response_model=AuthStatusResponse)
def auth_demo() -> AuthStatusResponse:
    return ig_service.start_demo_mode()


@app.post("/api/auth/logout", response_model=AuthStatusResponse)
def auth_logout() -> AuthStatusResponse:
    if job_manager.is_active():
        job_manager.stop()
    ig_service.logout()
    return ig_service.get_status()


# ------------------------------------------------------------------
# Whitelist Routes
# ------------------------------------------------------------------
@app.get("/api/whitelist")
def list_whitelist() -> dict:
    return {"usernames": ig_service.get_whitelist()}


@app.post("/api/whitelist")
def add_whitelist(req: WhitelistRequest) -> dict:
    return {"usernames": ig_service.add_whitelist(req.username)}


@app.delete("/api/whitelist/{username}")
def remove_whitelist(username: str) -> dict:
    return {"usernames": ig_service.remove_whitelist(username)}


# ------------------------------------------------------------------
# DM Routes
# ------------------------------------------------------------------
@app.get("/api/dm/threads", response_model=list[ThreadItem])
async def get_dm_threads(amount: int = Query(default=50, ge=1, le=200)) -> list[ThreadItem]:
    try:
        return await asyncio.to_thread(ig_service.get_threads, amount)
    except InstagramAuthError as exc:
        raise HTTPException(status_code=401, detail={"code": exc.code, "message": str(exc)}) from exc
    except InstagramRateLimitError as exc:
        raise HTTPException(status_code=429, detail={"code": "RATE_LIMITED", "message": str(exc)}) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"code": "DM_FETCH_ERROR", "message": str(exc)}) from exc


@app.post("/api/dm/search", response_model=list[MessageMatchItem])
async def search_dm_messages(req: SearchMessagesRequest) -> list[MessageMatchItem]:
    try:
        return await asyncio.to_thread(
            ig_service.search_messages,
            req.keyword,
            req.thread_ids,
            req.limit_per_thread,
            req.only_mine,
            req.case_sensitive,
        )
    except InstagramAuthError as exc:
        raise HTTPException(status_code=401, detail={"code": exc.code, "message": str(exc)}) from exc
    except InstagramRateLimitError as exc:
        raise HTTPException(status_code=429, detail={"code": "RATE_LIMITED", "message": str(exc)}) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"code": "DM_SEARCH_ERROR", "message": str(exc)}) from exc


@app.post("/api/dm/delete-threads", response_model=JobStatusResponse)
async def delete_dm_threads(req: DeleteThreadsRequest) -> JobStatusResponse:
    if not ig_service.authenticated:
        raise HTTPException(status_code=401, detail={"code": "NOT_AUTHENTICATED", "message": "Giriş yapmalısınız."})
    try:
        return job_manager.start_delete_threads(req)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail={"code": "JOB_BUSY", "message": str(exc)}) from exc


@app.post("/api/dm/unsend", response_model=JobStatusResponse)
async def unsend_dm_messages(req: UnsendMessagesRequest) -> JobStatusResponse:
    if not ig_service.authenticated:
        raise HTTPException(status_code=401, detail={"code": "NOT_AUTHENTICATED", "message": "Giriş yapmalısınız."})
    try:
        return job_manager.start_unsend_messages(req)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail={"code": "JOB_BUSY", "message": str(exc)}) from exc


# ------------------------------------------------------------------
# Story Archive Routes
# ------------------------------------------------------------------
@app.get("/api/stories/archive", response_model=list[StoryArchiveItem])
async def get_archived_stories(limit: int = Query(default=100, ge=1, le=300)) -> list[StoryArchiveItem]:
    try:
        return await asyncio.to_thread(ig_service.get_archived_stories, limit)
    except InstagramAuthError as exc:
        raise HTTPException(status_code=401, detail={"code": exc.code, "message": str(exc)}) from exc
    except InstagramRateLimitError as exc:
        raise HTTPException(status_code=429, detail={"code": "RATE_LIMITED", "message": str(exc)}) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"code": "STORY_FETCH_ERROR", "message": str(exc)}) from exc


@app.post("/api/stories/delete", response_model=JobStatusResponse)
async def delete_archived_stories(req: DeleteStoriesRequest) -> JobStatusResponse:
    if not ig_service.authenticated:
        raise HTTPException(status_code=401, detail={"code": "NOT_AUTHENTICATED", "message": "Giriş yapmalısınız."})
    try:
        return job_manager.start_delete_stories(req)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail={"code": "JOB_BUSY", "message": str(exc)}) from exc


# ------------------------------------------------------------------
# All Clean Route
# ------------------------------------------------------------------
@app.post("/api/clean/all", response_model=JobStatusResponse)
async def start_all_clean(req: AllCleanRequest) -> JobStatusResponse:
    if not ig_service.authenticated:
        raise HTTPException(status_code=401, detail={"code": "NOT_AUTHENTICATED", "message": "Giriş yapmalısınız."})
    if not req.delete_dm_threads and not req.delete_archived_stories:
        raise HTTPException(
            status_code=400,
            detail={"code": "NOTHING_SELECTED", "message": "En az bir temizlik seçeneği seçmelisiniz."},
        )
    try:
        return job_manager.start_all_clean(req)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail={"code": "JOB_BUSY", "message": str(exc)}) from exc


# ------------------------------------------------------------------
# Job Control Routes
# ------------------------------------------------------------------
@app.get("/api/jobs/status", response_model=JobStatusResponse)
def get_job_status() -> JobStatusResponse:
    return job_manager.get_status()


@app.post("/api/jobs/pause", response_model=JobStatusResponse)
def pause_job() -> JobStatusResponse:
    return job_manager.pause()


@app.post("/api/jobs/resume", response_model=JobStatusResponse)
def resume_job() -> JobStatusResponse:
    return job_manager.resume()


@app.post("/api/jobs/stop", response_model=JobStatusResponse)
def stop_job() -> JobStatusResponse:
    return job_manager.stop()


# ------------------------------------------------------------------
# Frontend Static Files & PWA Entrypoint
# ------------------------------------------------------------------
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/manifest.json")
def serve_manifest() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "manifest.json", media_type="application/manifest+json")


@app.get("/sw.js")
def serve_sw() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "sw.js", media_type="application/javascript")


@app.get("/")
def serve_index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")
