import asyncio
import hmac
import json
import re
import secrets
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from livekit import api
from pydantic import BaseModel, Field

from .config import ROOT, Settings, settings
from .contacts import Contacts
from .docupdates import DocUpdates, UpdateExpired
from .engine import TERMINAL, ControlError, Coordinator
from .notifications import NotificationUnconfirmed, briefing_message, send_slack
from .providers import livekit_api, lk_token, readiness
from .store import SEED, Store


class Login(BaseModel):
    password: str = Field(max_length=500)


class Access(BaseModel):
    token: str = Field(max_length=2000)


class Start(BaseModel):
    mode: Literal["phone", "browser"] = "phone"
    scenario: Literal["standard", "pitch"] = "standard"


class Command(BaseModel):
    action: Literal["takeover", "handback", "unavailable", "pause", "end", "dtmf"]
    request_id: str = Field(min_length=8, max_length=100)
    revision: int = Field(ge=0)
    digits: str = Field(default="", max_length=12)


class EditCase(BaseModel):
    patient: str = Field(min_length=1, max_length=100)
    date_of_birth: str = Field(max_length=20)
    member_id: str = Field(max_length=100)
    provider: str = Field(max_length=100)
    provider_npi: str = Field(max_length=30)
    practice: str = Field(max_length=100)
    medication: str = Field(max_length=100)
    dose: str = Field(max_length=100)
    payer: str = Field(max_length=100)
    diagnosis: str = Field(max_length=500)
    request: str = Field(max_length=2000)
    evidence: str = Field(max_length=8000)


def create_app(config: Settings = settings, transport_factory=None):
    signer = URLSafeTimedSerializer(config.secret(), salt="atp-demo")
    store = Store(config.db_path)
    coordinator = Coordinator(config, store, transport_factory)
    attempts = {}
    used_links = set()

    def public_url():
        if config.public_base_url.startswith("https://"):
            return config.public_base_url.rstrip("/")
        path = ROOT / ".local/public-url"
        if path.exists():
            value = path.read_text().strip()
            if re.fullmatch(r"https://[a-z0-9-]+\.trycloudflare\.com", value):
                return value
        return ""

    async def notify_doctor(call, attempt):
        try:
            token = signer.dumps(
                {
                    "purpose": "invite",
                    "role": "doctor",
                    "call_id": call["id"],
                    "identity": attempt["identity"],
                    "phone_control": True,
                    "nonce": secrets.token_hex(6),
                }
            )
            base = public_url()
            link = base + "/join#" + token if base else ""
            attempt["control_url"] = link
            attempt["notification_provider"] = "slack"
            await send_slack(config, briefing_message(call, attempt, link))
            attempt["notification_status"] = "posted"
        except Exception as exc:
            attempt["notification_status"] = (
                "unconfirmed" if isinstance(exc, NotificationUnconfirmed) else "failed"
            )
            attempt["notification_error"] = (
                str(exc)
                if isinstance(exc, RuntimeError)
                else "Slack message could not be confirmed. Check the webhook and channel."
            )
        finally:
            if coordinator.call is call:
                coordinator.emit()

    coordinator.notify_doctor = notify_doctor

    def update_completion(saved_call):
        if coordinator.call and coordinator.call["id"] == saved_call["id"]:
            coordinator.call["docupdates"] = saved_call["docupdates"]
            coordinator.emit()

    docupdates = DocUpdates(config, store, public_url, update_completion)
    coordinator.notify_completion = docupdates.enqueue

    @asynccontextmanager
    async def lifespan(app):
        stale = [c for c in store.calls() if c["status"] not in TERMINAL]
        coordinator.recover()
        docupdates.recover()
        # Reconcile only this application's persisted rooms.
        if stale and config.livekit_api_key:
            try:
                async with livekit_api(config) as lk:
                    for call in stale:
                        await lk.room.delete_room(api.DeleteRoomRequest(room=call["room"]))
            except Exception:
                pass
        yield
        if coordinator.call and coordinator.call["status"] not in TERMINAL:
            await coordinator.end("Application shutting down.")
        await docupdates.close()
        store.close()

    app = FastAPI(title="ATP", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.coordinator = coordinator
    app.state.signer = signer
    app.state.docupdates = docupdates

    @app.middleware("http")
    async def security_headers(request, call_next):
        if request.url.path.startswith("/api/") and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if request.headers.get("x-atp-request") != "1":
                return JSONResponse({"detail": "Missing request header."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        if request.url.path.startswith("/api/docupdates/"):
            # Only the hosted reader gets cross-origin access; operator APIs stay unchanged.
            from urllib.parse import urlsplit

            frontend = urlsplit(config.docupdates_base_url)
            allowed_origin = f"{frontend.scheme}://{frontend.netloc}"
            response.headers["Vary"] = "Origin"
            if request.headers.get("origin") == allowed_origin:
                response.headers["Access-Control-Allow-Origin"] = allowed_origin
        return response

    @app.exception_handler(ControlError)
    async def control_error(request, exc):
        return JSONResponse({"detail": exc.message}, status_code=exc.status)

    def decode(token, purpose="session"):
        try:
            data = signer.loads(token, max_age=7200)
            if data.get("purpose") != purpose:
                raise BadSignature("purpose")
            return data
        except (BadSignature, SignatureExpired):
            raise HTTPException(401, "Session expired. Open a new join link or sign in again.")

    def auth(request: Request):
        bearer = request.headers.get("authorization", "")
        token = bearer[7:] if bearer.startswith("Bearer ") else request.cookies.get("atp_session", "")
        return decode(token)

    def operator(request):
        data = auth(request)
        if data["role"] != "operator":
            raise HTTPException(403, "Operator access required.")
        return data

    def call_auth(request, call_id):
        data = auth(request)
        if data["role"] != "operator" and data.get("call_id") != call_id:
            raise HTTPException(403, "This link belongs to another call.")
        if not coordinator.call or coordinator.call["id"] != call_id:
            raise HTTPException(404, "Call is no longer active in this session.")
        return data

    @app.get("/api/health")
    async def health():
        return {"ok": True, "product": "ATP"}

    @app.get("/api/docupdates/{token}")
    async def authorization_update(token: str):
        try:
            record = docupdates.lookup(token)
        except UpdateExpired:
            raise HTTPException(410, "This authorization update link has expired.")
        if not record:
            raise HTTPException(404, "Authorization update not found.")
        return record

    @app.post("/api/login")
    async def login(body: Login, request: Request, response: Response):
        ip = request.client.host if request.client else "unknown"
        now = time.time()
        attempts[ip] = [t for t in attempts.get(ip, []) if t > now - 60]
        if len(attempts[ip]) >= 8:
            raise HTTPException(429, "Too many attempts. Try again in a minute.")
        attempts[ip].append(now)
        if not config.app_demo_password or not hmac.compare_digest(
            body.password.encode(), config.app_demo_password.encode()
        ):
            raise HTTPException(401, "Incorrect password.")
        attempts[ip] = []
        token = signer.dumps({"role": "operator", "purpose": "session"})
        response.set_cookie(
            "atp_session",
            token,
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
            max_age=7200,
        )
        return {"role": "operator"}

    @app.post("/api/logout")
    async def logout(response: Response):
        response.delete_cookie("atp_session")
        return {"ok": True}

    @app.get("/api/session")
    async def session(request: Request):
        return auth(request)

    @app.post("/api/access")
    async def access(body: Access):
        data = decode(body.token, "invite")
        if body.token in used_links:
            raise HTTPException(401, "This link was already used. Ask for a fresh join link.")
        if not coordinator.call or data["call_id"] != coordinator.call["id"]:
            raise HTTPException(404, "This call is unavailable.")
        used_links.add(body.token)
        data["purpose"] = "session"
        return {"token": signer.dumps(data), **{k: data[k] for k in ("role", "call_id", "identity")}}

    @app.get("/api/readiness")
    async def ready(request: Request):
        operator(request)
        result = await readiness(config)
        coordinator.ready_checks = result
        return result

    @app.get("/api/contacts")
    async def get_contacts(request: Request):
        operator(request)
        return coordinator.contacts

    @app.put("/api/contacts")
    async def save_contacts(body: Contacts, request: Request):
        operator(request)
        if coordinator.call and coordinator.call["status"] not in TERMINAL:
            raise HTTPException(409, "End the active call before changing phone numbers.")
        if config.plivo_phone_number and config.plivo_phone_number in {
            body.insurer_phone_number,
            body.doctor_phone_number,
        }:
            raise HTTPException(
                422, "Use the insurer and doctor's receiving numbers, not ATP's caller number."
            )
        coordinator.contacts = body.model_dump()
        store.put("contacts", coordinator.contacts)
        return coordinator.contacts

    @app.post("/api/calls/{call_id}/call-doctor")
    async def call_doctor(call_id: str, request: Request):
        operator(request)
        call_auth(request, call_id)
        if coordinator.call["status"] in TERMINAL:
            raise HTTPException(409, "The call has ended.")
        coordinator.request_doctor()
        return coordinator.snapshot(True)

    @app.get("/api/case")
    async def get_case(request: Request):
        operator(request)
        return store.get("case")

    @app.patch("/api/case")
    async def edit_case(body: EditCase, request: Request):
        operator(request)
        if coordinator.call and coordinator.call["status"] not in TERMINAL:
            raise HTTPException(409, "End the call before editing the source case.")
        case = {"id": SEED["id"], **body.model_dump()}
        store.put("case", case)
        return case

    @app.get("/api/calls")
    async def calls(request: Request):
        operator(request)
        return {
            "current": coordinator.snapshot(True),
            "history": [
                {"id": c["id"], "status": c["status"], "created_at": c["created_at"]} for c in store.calls()
            ],
        }

    @app.post("/api/calls")
    async def start(body: Start, request: Request):
        operator(request)
        required = [
            "openai_api_key",
            "eleven_api_key",
            "eleven_voice_id",
            "livekit_url",
            "livekit_api_key",
            "livekit_api_secret",
        ]
        if body.mode == "phone":
            required += ["plivo_phone_number"]
            if not all(coordinator.contacts.get(k) for k in ("insurer_phone_number", "doctor_phone_number")):
                raise HTTPException(
                    422, "Save both the insurer and doctor phone numbers in Call destinations first."
                )
        if any(not getattr(config, name) for name in required):
            raise HTTPException(503, "Required service configuration is missing. Run make doctor.")
        return await coordinator.start(body.mode, body.scenario)

    @app.get("/api/calls/{call_id}")
    async def get_call(call_id: str, request: Request):
        data = call_auth(request, call_id)
        return coordinator.snapshot(data["role"] in {"operator", "administrator", "doctor"})

    @app.post("/api/calls/{call_id}/join-links")
    async def links(call_id: str, request: Request):
        operator(request)
        call_auth(request, call_id)
        roles = ["administrator", "doctor", "presentation"]
        if coordinator.call["mode"] == "browser":
            roles.append("payer")
        base = str(request.base_url).rstrip("/")
        runtime_path = ROOT / ".local" / "public-url"
        if runtime_path.exists():
            public = runtime_path.read_text().strip()
            if re.fullmatch(r"https://[a-z0-9-]+\.trycloudflare\.com", public):
                base = public
        result = {}
        for role in roles:
            identity = "payer" if role == "payer" else role + "-" + secrets.token_hex(5)
            token = signer.dumps(
                {
                    "purpose": "invite",
                    "role": role,
                    "call_id": call_id,
                    "identity": identity,
                    "nonce": secrets.token_hex(6),
                }
            )
            result[role] = base + "/join#" + token
        return result

    @app.post("/api/calls/{call_id}/join")
    async def join(call_id: str, request: Request):
        data = call_auth(request, call_id)
        if coordinator.call["status"] in TERMINAL:
            raise HTTPException(409, "This call has ended.")
        role = data["role"]
        if data.get("phone_control"):
            raise HTTPException(
                409, "Your audio is on the incoming phone call. This page supplies controls only."
            )
        identity = data.get("identity", "operator-monitor")
        coordinator.session_participants[identity] = role
        return {
            "url": config.livekit_url,
            "token": lk_token(config, coordinator.call["room"], identity, role == "payer"),
            "identity": identity,
        }

    @app.post("/api/calls/{call_id}/control")
    async def control(call_id: str, body: Command, request: Request):
        data = call_auth(request, call_id)
        return await coordinator.control(
            data["role"], body.action, body.request_id, body.revision, data.get("identity", ""), body.digits
        )

    @app.get("/api/calls/{call_id}/export")
    async def export(call_id: str, request: Request):
        operator(request)
        saved = store.get("call:" + call_id)
        if not saved:
            raise HTTPException(404, "Call not found.")
        saved.pop("briefing", None)
        return JSONResponse(
            saved, headers={"Content-Disposition": f'attachment; filename="atp-{call_id}.json"'}
        )

    @app.get("/api/history/{call_id}")
    async def history_call(call_id: str, request: Request):
        operator(request)
        saved = store.get("call:" + call_id)
        if not saved:
            raise HTTPException(404, "Call not found.")
        return saved

    @app.websocket("/api/calls/{call_id}/events")
    async def events(ws: WebSocket, call_id: str):
        origin = ws.headers.get("origin")
        from urllib.parse import urlparse

        if origin and urlparse(origin).netloc != ws.headers.get("host"):
            await ws.close(code=4403)
            return
        await ws.accept()
        try:
            hello = await asyncio.wait_for(ws.receive_json(), timeout=5)
            if not isinstance(hello, dict):
                raise HTTPException(401)
            token = hello.get("token") or ws.cookies.get("atp_session", "")
            if not isinstance(token, str):
                raise HTTPException(401)
            data = decode(token)
            if data["role"] != "operator" and data.get("call_id") != call_id:
                raise HTTPException(403)
            if not coordinator.call or coordinator.call["id"] != call_id:
                raise HTTPException(404)
        except (HTTPException, TimeoutError, json.JSONDecodeError, WebSocketDisconnect):
            await ws.close(code=4401)
            return
        queue = asyncio.Queue(maxsize=100)
        coordinator.listeners.add(queue)
        private = data["role"] in {"operator", "administrator", "doctor"}
        try:
            await ws.send_json({"type": "snapshot", "call": coordinator.snapshot(private)})
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    await ws.send_json({"type": "ping"})
                    continue
                if event["call_id"] != call_id:
                    await ws.close(code=1000)
                    break
                if event["type"] == "partial":
                    await ws.send_json(event)
                else:
                    await ws.send_json({"type": "snapshot", "call": coordinator.snapshot(private)})
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            coordinator.listeners.discard(queue)

    dist = ROOT / "web" / "dist"
    if (dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}")
    async def frontend(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        if not (dist / "index.html").exists():
            return JSONResponse({"detail": "Build frontend first: make setup"}, status_code=503)
        return FileResponse(dist / "index.html")

    return app


app = create_app()
