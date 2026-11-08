# Reaching agents-dialpad from your phone

agents-dialpad listens on `127.0.0.1` only. To use it from another device you need a **private** path to your computer.
Pick one below. Whatever you choose, never expose the port to the public internet: anyone who reaches it and has the
token can start agents on your machine.

## Why HTTPS matters

The installable app (service worker), the clipboard "Copy" button and "Add to Home Screen" need a **secure context**:
HTTPS, or `localhost`. Plain `http://192.168.x.x` works for basic chatting in a browser tab, but you lose installation,
and traffic (including your token header) is unencrypted on your network. Prefer one of the HTTPS options.

## Option 1: Tailscale (recommended)

A private network between your own devices, with free HTTPS certificates. No ports opened on your router.

1. Install Tailscale on the computer and the phone and sign in to the same account.
2. In the Tailscale admin console, enable **MagicDNS** and **HTTPS Certificates**.
3. On the computer:
   ```bash
   tailscale serve status                       # see what is already published; do not overwrite it
   tailscale serve --bg --https=8443 8787       # publish agents-dialpad on its own port (8787 is the default)
   ```
   Use a dedicated HTTPS port (8443 here). Plain `tailscale serve --bg 8787` takes over port 443 and would replace
   anything already published there. Undo with `tailscale serve --https=8443 off`.
4. On the phone (Tailscale connected) open `https://<machine>.<tailnet>.ts.net:8443/#token=<token>`
   (`agents-dialpad token` prints it), then Add to Home Screen.

`agents-dialpad doctor` checks the Tailscale connection and whether this mapping exists.

**Do not use Tailscale Funnel**: it publishes to the whole internet.

## Option 2: Cloudflare Tunnel with Cloudflare Access

Works from anywhere without installing a VPN app on the phone, but it is a public hostname, so you **must** put
Cloudflare Access (SSO or one-time email codes) in front of it. The access token alone is not enough protection for a
tool that can run commands.

1. Create a tunnel with `cloudflared` pointing at `http://127.0.0.1:8787`.
2. Create an Access application for that hostname with a policy that allows only you.
3. Open the hostname on your phone, sign in through Access, then enter the token as usual.

If you cannot enforce Access, use Tailscale instead.

## Option 3: SSH tunnel

If you already use an SSH client on your phone, forward a local port to the computer's `127.0.0.1:8787`
(`ssh -L 8787:127.0.0.1:8787 you@your-computer`) and browse to `http://localhost:8787` on the phone. `localhost` counts as
a secure context, so the app works. The computer must run an SSH server reachable only over a network you trust.

## Option 4: Same Wi-Fi only (not recommended)

Set `"host": "0.0.0.0"` in `config.json` and browse to `http://<computer-ip>:8787`. This exposes the port to everyone on
that network over plain HTTP. Only do it on a network you fully control, and prefer Tailscale.

## Hygiene

- The token is a password. Anyone with it can use your agents. Rotate it with `agents-dialpad token --rotate`.
- Leave "Full access" off unless you need it, and only open projects you trust.
- Do not port-forward, and do not publish the port with any tool that has no authentication in front of it.
