# Deploying (single-origin)

The backend serves the built frontend as static files from `backend/app/static/`.
By default that directory only contains a placeholder `index.html` — nothing
copies the real build there automatically.

To produce a real production deployment:

1. From `frontend/`, run `npm run build:backend`. This type-checks and builds
   the app straight into `backend/app/static/` (replacing the placeholder).
2. Run the backend normally, e.g. `uvicorn app.main:app`. It will now serve
   the built React app at `/` instead of the placeholder.

The default `npm run build` script is unaffected and still builds to
`frontend/dist/` for local inspection or other deployment setups.
