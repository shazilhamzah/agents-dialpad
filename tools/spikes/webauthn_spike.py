"""FastAPI spike for WebAuthn passkey registration and authentication."""
from __future__ import annotations

import base64
import json
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

import webauthn
from webauthn import (
    generate_registration_options,
    verify_registration_response,
    generate_authentication_options,
    verify_authentication_response,
    options_to_json,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    UserVerificationRequirement,
    AuthenticatorAttachment,
    ResidentKeyRequirement,
    PublicKeyCredentialDescriptor,
)

app = FastAPI(title="WebAuthn Spike")
PAGE_HTML = (Path(__file__).parent / "webauthn_page.html").read_text(encoding="utf-8")

# In-memory storage for the spike
CREDENTIALS: dict[str, dict] = {}
CURRENT_CHALLENGE: dict[str, bytes] = {}


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE_HTML


@app.get("/version")
def version():
    return {"version": webauthn.__version__}


@app.post("/register/options")
async def register_options(request: Request):
    data = await request.json()
    username = data.get("username", "testuser")
    rp_id = request.url.hostname or "localhost"

    opts = generate_registration_options(
        rp_name="agents-dialpad Spike",
        rp_id=rp_id,
        user_id=username.encode("utf-8"),
        user_name=username,
        user_display_name=username,
        authenticator_selection=AuthenticatorSelectionCriteria(
            authenticator_attachment=AuthenticatorAttachment.PLATFORM,
            user_verification=UserVerificationRequirement.REQUIRED,
            resident_key=ResidentKeyRequirement.PREFERRED,
        ),
    )
    CURRENT_CHALLENGE["reg"] = opts.challenge
    return JSONResponse(json.loads(options_to_json(opts)))


@app.post("/register/verify")
async def register_verify(request: Request):
    body = await request.json()
    rp_id = request.url.hostname or "localhost"
    origin = f"{request.url.scheme}://{request.url.netloc}"
    challenge = CURRENT_CHALLENGE.pop("reg", b"")

    try:
        ver = verify_registration_response(
            credential=body,
            expected_challenge=challenge,
            expected_origin=origin,
            expected_rp_id=rp_id,
            require_user_verification=True,
        )
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    cred_id = base64.urlsafe_b64encode(ver.credential_id).decode("utf-8").rstrip("=")
    pub_key = base64.urlsafe_b64encode(ver.credential_public_key).decode("utf-8").rstrip("=")
    CREDENTIALS[cred_id] = {
        "credential_id": ver.credential_id,
        "public_key": ver.credential_public_key,
        "sign_count": ver.sign_count,
        "rp_id": rp_id,
    }
    return {"ok": True, "credential_id": cred_id}


@app.post("/authenticate/options")
async def auth_options(request: Request):
    rp_id = request.url.hostname or "localhost"
    allow_credentials = [
        PublicKeyCredentialDescriptor(id=c["credential_id"])
        for c in CREDENTIALS.values()
    ]
    opts = generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=allow_credentials or None,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    CURRENT_CHALLENGE["auth"] = opts.challenge
    return JSONResponse(json.loads(options_to_json(opts)))


@app.post("/authenticate/verify")
async def auth_verify(request: Request):
    body = await request.json()
    rp_id = request.url.hostname or "localhost"
    origin = f"{request.url.scheme}://{request.url.netloc}"
    challenge = CURRENT_CHALLENGE.pop("auth", b"")

    raw_id_b64 = body.get("rawId") or body.get("id")
    # Pad b64url
    pad = len(raw_id_b64) % 4
    if pad:
        raw_id_b64 += "=" * (4 - pad)
    raw_id = base64.urlsafe_b64decode(raw_id_b64)

    cred = next((c for c in CREDENTIALS.values() if c["credential_id"] == raw_id), None)
    if not cred:
        return JSONResponse({"ok": False, "error": "Unknown credential"}, status_code=404)

    try:
        ver = verify_authentication_response(
            credential=body,
            expected_challenge=challenge,
            expected_origin=origin,
            expected_rp_id=rp_id,
            credential_public_key=cred["public_key"],
            credential_current_sign_count=cred["sign_count"],
            require_user_verification=True,
        )
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    cred["sign_count"] = ver.new_sign_count
    return {"ok": True, "new_sign_count": ver.new_sign_count}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8799)
