import uvicorn

from .app import CFG, TOKEN, app


def main() -> None:
    host, port = CFG["host"], CFG["port"]
    print("\nagents-dialpad")
    print(f"  Local URL  : http://127.0.0.1:{port}/#token={TOKEN}")
    print(f"  Token      : static, from {CFG['_token_source']} (same on every run)")
    print("  (open the link once per device; the token is saved in the browser and removed from the URL)")
    print(f"  Instructions: {CFG.get('instructions_file') or 'none'}")
    print(f"  Projects   : {', '.join(f'{k} -> {v}' for k, v in CFG['projects'].items())}")
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(f"  WARNING    : listening on {host}; anyone who can reach this port and has the token can run agents here.")
    print()
    # No reload: on Windows it swaps the event loop and breaks subprocess handling.
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
