# G0 Spike Findings: File Viewer on Mobile and Desktop

**Date:** 2026-11-10
**Context:** Tasks G0–G6 for agents-dialpad file viewer

---

## 1. PDF on iPhone Safari & Android Chrome (Tested against web standards / known browser limits)

- **iPhone Safari (iOS):** `<iframe src="blob:...">` and `<object data="blob:...">` only render the first page of multi-page PDFs. iOS WebKit does not provide embedded multi-page scrolling controls inside iframes.
- **Android Chrome:** `<iframe src="blob:...">` does not render PDF inline; Android Chrome lacks an embedded PDF plugin for iframe contexts, triggering a download prompt or displaying an empty grey frame.
- **Decision:** Path A (native iframe) is rejected. **G4 must implement Path B: vendor pdf.js**, rendering pages to `<canvas>` via `IntersectionObserver`.

---

## 2. FileResponse + Range on Starlette 1.10 / FastAPI 0.162 (Verified in Python)

- `FileResponse` in Starlette natively supports HTTP `Range` requests:
  - Request with `Range: bytes=0-99` returns HTTP `206 Partial Content`.
  - Headers returned include `Content-Range: bytes 0-99/<total>` and `Content-Length: 100`.
- Custom security headers (`X-Content-Type-Options: nosniff`, `Cache-Control: no-store`, `Content-Security-Policy: sandbox; ...`) are preserved on both 200 and 206 responses.
- `Content-Disposition` for non-ASCII filenames must use RFC 5987 formatting:
  `inline; filename="{ascii_fallback}"; filename*=UTF-8''{quote(name)}`
  where `ascii_fallback` strips non-printable ASCII and quotes/backslashes.

---

## 3. Sandbox CSP on Blob Fetches (Verified)

- Response CSP:
  `Content-Security-Policy: sandbox; default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'`
- When the client performs `fetch()` -> `Blob` -> `URL.createObjectURL(blob)`:
  - Raster images and SVG loaded in `<img>` display properly.
  - In an `<img>` tag, SVGs cannot execute JavaScript, protecting `localStorage` and app tokens.
  - Files are never inserted into the page DOM via `innerHTML` or as un-sandboxed frames.

---

## 4. HEIC Support (Verified specifications)

- Safari on iOS and macOS natively displays HEIC images in `<img>`.
- Chrome and Firefox on Android / Windows do not support HEIC in `<img>`.
- Fallback strategy: The UI attempts to load the image blob into `<img>`. If an `error` event fires, it gracefully displays the metadata card with an "Image format not supported for preview; use Download" message.

---

## 5. App Lock / 423 Path with `api()` (Verified)

- In `app.js`, `api(path, opts)` detects HTTP 423 (Locked).
- It calls `await promptUnlock()`, updates the `X-Unlock` session header, and retries the request.
- The returned `Response` object allows calling `await r.blob()` without issues on the retry.

---

## 6. Mobile Memory & Hardware Limits (Documented requirement for owner)

- Large PDFs or multi-megapixel images in blob URLs can consume significant RAM in mobile WebKit / Chrome.
- Caps:
  - Preview size cap: 50 MB. Files exceeding 50 MB show the metadata card with Download only.
  - Text preview cap: 1 MB server-side (`X-Truncated: 1`).
  - pdf.js rendering: render visible pages only, cap `devicePixelRatio` at 2.
- **Hardware testing status:** Physical iPhone Safari and physical Android Chrome testing could not be performed in the current headless/desktop environment. The owner must test opening 20+ page PDFs and 12MP images on real devices.

---

## 7. pdf.js Vendoring Details (for G4)

- **License:** Apache License 2.0 (compatible with dialtone MIT license).
- **Files needed:** `pdf.min.mjs`, `pdf.worker.min.mjs`, and `LICENSE` in `agents_dialpad/static/vendor/pdfjs/`.
- **Loading:** Dynamic `import('/vendor/pdfjs/pdf.min.mjs')` loaded lazily only when opening a PDF. Not included in the service worker boot shell cache.
- **Isolation:** Disable remote font/cmap network fetching to obey Golden Rules 7 and 8 (no requests leaving origin).
