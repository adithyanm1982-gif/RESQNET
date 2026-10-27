# RESQNET Frontend

React and Vite client for the RESQNET simulation API.

## Local development

Copy `.env.example` to `.env` and leave `VITE_BACKEND_URL` blank. The browser uses same-origin `/api` requests and Vite proxies them to `http://127.0.0.1:8000` during development.

```powershell
npm ci
npm run dev
```

## Deployment

Keep the existing Vercel project rooted at `frontend`. Set its production environment variable `VITE_BACKEND_URL` to the Railway backend's public origin, with no trailing slash. The backend must allow `https://resqnet-eight-psi.vercel.app` in `CORS_ORIGINS`.

Google sign-in is configured by `GOOGLE_CLIENT_ID` on the backend. Add the
frontend origin to the Google web client's **Authorized JavaScript origins**
and to backend `CORS_ORIGINS`. The backend returns the public client ID via
`GET /api/auth/config`; the frontend does not need a separate client-ID value.
See the backend README's **Google sign-in** section for local and production
cookie settings and the implemented auth API contract.

The Mission and Experiments pages install the selected dataset failure schedule before simulation ticks begin. Event lifecycle is returned by the backend; consult the Mission page's notes for which failure effects are operationally modeled.
