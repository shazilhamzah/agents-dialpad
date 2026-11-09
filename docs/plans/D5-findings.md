# D5 Spike Findings: WebAuthn Passkeys for App Lock

**Date:** 2026-11-09
**Library:** `webauthn` (py_webauthn) version `3.0.1`

## 1. Library Verification

The following core symbols required by the design exist and operate as expected in `webauthn 3.0.1`:
- `generate_registration_options`
- `verify_registration_response`
- `generate_authentication_options`
- `verify_authentication_response`
- `options_to_json`
- Helper structs: `AuthenticatorSelectionCriteria`, `UserVerificationRequirement`, `AuthenticatorAttachment`, `ResidentKeyRequirement`, `PublicKeyCredentialDescriptor`

## 2. Platform Compatibility

| Platform / Browser | `isUserVerifyingPlatformAuthenticatorAvailable()` | Native Biometric Sheet | Home Screen / PWA Persistence | Notes |
|---|---|---|---|---|
| **Desktop Chrome (Windows / macOS / Linux)** | `true` | Windows Hello / Touch ID prompt appears | Yes, passkey stored in OS platform authenticator | Works on `localhost` and `127.0.0.1` secure contexts |
| **Android Chrome (Phone / Tablet)** | `true` | Fingerprint / Screen lock / Passkey prompt appears | Yes, passkey retained across launches | Works on Tailscale HTTPS origin and `localhost` |
| **iOS / iPadOS Home Screen App (Safari PWA)** | `true` (iOS 16.4+) | Face ID / Touch ID prompt appears | Yes, WebAuthn credentials in Keychain persist | Secure context required (Tailscale HTTPS) |

## 3. Key Observations & Considerations

1. **Secure Context Requirement:**
   - WebAuthn APIs (`navigator.credentials.create` and `navigator.credentials.get`) are only available in a Secure Context (`window.isSecureContext === true`).
   - Plain HTTP LAN addresses (e.g. `http://192.168.1.x:8787`) fail with `PublicKeyCredential is not defined` or security errors.
   - Tailscale Serve HTTPS (e.g. `https://<device>.ts.net:8443`) and `http://127.0.0.1` / `http://localhost` are secure contexts where WebAuthn functions properly.

2. **Relying Party ID (`rp_id`):**
   - The RP ID must match the current host name (`location.hostname`). A passkey registered under `localhost` cannot authenticate under a Tailscale DNS name.
   - This matches the plan requirement: each registered passkey stores `rp_id` and the UI shows which origin it belongs to.

3. **No Breaking Blockers Found:**
   - iOS 16.4+ standalone Home Screen apps support WebAuthn and Face ID/Touch ID without issue. We can proceed with Part 1 (Server `agents_dialpad/applock.py`, CLI, Web UI, and integration).
