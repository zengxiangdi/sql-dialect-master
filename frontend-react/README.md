# SQL Dialect Master React workspace

This directory contains the React + TypeScript migration target. It runs next
to the existing Streamlit workspace while API and behavior parity are being
validated.

```bash
npm install
npm run dev
```

The Vite proxy runs on port `5174` and sends `/api`, `/health`, and `/ready` to the local FastAPI
server at `http://127.0.0.1:8000`. Set `VITE_API_BASE_URL` for a deployed API.
The Settings page can store an API base URL and optional API key in browser
local storage.

Port overrides are available with `VITE_PORT` and `VITE_PREVIEW_PORT`; the
defaults are `5174` and `4174` to avoid common local dashboard port conflicts.

Quality gates:

```bash
npm run lint
npm run typecheck
npm test
npm run build
```

The production build is emitted to `dist/` and can be served by a static web
server or CDN. FastAPI remains an API service; configure `SDM_ALLOWED_ORIGINS`
with the deployed React origin.
