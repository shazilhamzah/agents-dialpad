# D5 Spike Findings: WebAuthn Passkeys for App Lock

**Date:** 2026-11-09
**Library:** `webauthn` (py_webauthn) version `3.0.1`

## 1. Library verification (tested)

These symbols exist and work in `webauthn 3.0.1` (run in this repo's `.venv`):
- `generate_registration_options`, `verify_registration_response`
- `generate_authentication_options`, `verify_authentication_response`, `options_to_json`
- Helper structs: `AuthenticatorSelectionCriteria`, `UserVerificationRequirement`, `AuthenticatorAttachment`, `ResidentKeyRequirement`, `PublicKeyCredentialDescriptor`

Also checked by running code:
- Both verify functions require `require_user_verification=True` when the options asked for `user_verification=REQUIRED`.
- `expected_origin` accepts a list; a response from an origin not in the list raises `InvalidRegistrationResponse`.
- A registration and an authentication made with a **software P-256 key** verify correctly. They are stored in
  `tests/fixtures/webauthn/recorded.json` and used by `tests/test_applock.py`.

## 2. Platform behaviour (NOT tested on hardware)

The spike page and server exist (`tools/spikes/webauthn_page.html`, `webauthn_spike.py`), but **they have not been run on
an iPhone, an Android phone or desktop Chrome**. The table below is what platform documentation says should happen. It is
not an observation. The plan says that if an iPhone Home Screen app cannot use passkeys, the design must change, so this
must be checked by hand before relying on it.

| Platform | Expected (from documentation) | Verified? |
|---|---|---|
| Desktop Chrome on `localhost` | Secure context; Windows Hello / Touch ID sheet | No |
| Android Chrome / Home Screen app on the Tailscale HTTPS address | Fingerprint or screen-lock sheet | No |
| iPhone Home Screen web app on the Tailscale HTTPS address (iOS 16.4+) | Face ID / Touch ID sheet; passkey survives closing the app | No |

What to record when you run it: does the system sheet appear, does authenticate still work after closing and reopening
the Home Screen app, and what does `PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable()` return.

## 3. Design points that do hold (from the WebAuthn standard, enforced in code)

1. WebAuthn only exists in a secure context (HTTPS or `localhost`). Plain-HTTP LAN addresses cannot use App lock; the UI says so.
2. The relying-party id must equal the host name the app is opened on, so a passkey made on one address does not work on another.
3. The server never builds allowed origins from the request's `Host` header.
