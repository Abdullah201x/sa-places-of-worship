# Security Policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Report them privately through
GitHub's "Report a vulnerability" button on the repository's **Security** tab
(private vulnerability reporting). Include what you found, how to reproduce it, and the impact.

You can expect an acknowledgement within a few days. This is a volunteer-run OpenStreetMap
tooling project, so please allow reasonable time for a fix before disclosing publicly.

## Scope

In scope: the FastAPI backend (`backend/`), the web client (`frontend/`), the data pipeline
(`pipeline/`), and the container/proxy configuration (`Dockerfile`, `deploy/`).

Out of scope: denial-of-service through volume, findings that need a compromised OSM account
or browser, and vulnerabilities in third-party services (OpenStreetMap, Esri, Wikidata, etc.).

## Design notes for reviewers

- Login is OpenStreetMap OAuth 2.0 with PKCE. The backend exchanges the OSM token for its own
  `HttpOnly` session cookie, stores only a SHA-256 hash of the session token, and discards the
  OSM token.
- State-changing requests require the `X-Manara-CSRF` header and an allow-listed `Origin`.
- The OSM dev server is only accepted when `MANARA_DEV_MODE` is set (local development).
- The Content-Security-Policy (`deploy/Caddyfile.container`) forbids inline scripts.
- Secrets live in environment variables; see `.env.example`. Nothing secret is committed.
