# Bijoy Devnath Portfolio — Backend

A small self-hosted API that replaces the Firebase (Firestore + Auth) calls
the site used to make. Built with Flask + SQLite — no external database or
paid service needed.

It covers everything the admin panel on the site uses:
- Admin login (JWT-based, single admin account)
- Projects (list / add / delete)
- Services (list / add / delete)
- Contact messages (public submit, admin list / delete)
- Site text settings (bio, stats, email, WhatsApp number)
- Basic page-view stats

## 1. Install

Requires Python 3.9+.

```bash
cd backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Configure

```bash
cp .env.example .env
```

Then edit `.env`:

- `ADMIN_EMAIL` / `ADMIN_PASSWORD` — the login you'll use in the site's
  admin panel (the 🔒 modal). **Change these from the example values.**
- `JWT_SECRET` — any long random string, used to sign login sessions.
  Generate one with:
  ```bash
  python -c "import secrets; print(secrets.token_hex(32))"
  ```
  If you leave this blank, the server makes up a random one each time it
  starts — fine for testing, but it means everyone gets logged out whenever
  the server restarts. Set a real value before you rely on this.
- `JWT_EXPIRY_DAYS` — how many days a login stays valid (default 7).

If you skip `.env` entirely and never set `ADMIN_EMAIL`/`ADMIN_PASSWORD`,
the server generates a one-time admin login and prints it to the console
the first time it runs — check the terminal output.

## 3. Run it

```bash
python app.py
```

By default this also serves the frontend (the `../frontend` folder) at
the same address, so opening `http://localhost:5000/` shows the full site
with the admin panel wired up. The API alone lives under `/api/...`.

Data is stored in `backend/data/site.db` (SQLite — a single file). Back it
up like any other file; delete it to start completely fresh (you'll get a
new random admin login unless `.env` sets one).

## 4. Point the frontend at it

Open `frontend/index.html` and find this near the top of the first
`<script>` block:

```js
const API_BASE = '';
```

- Leave it as `''` if Flask is serving both the frontend and the API from
  the same address (simplest — see step 3).
- If you host the frontend somewhere else (GitHub Pages, Netlify, Firebase
  Hosting, etc.) and only deploy this backend, change it to your backend's
  full URL, e.g.:
  ```js
  const API_BASE = 'https://your-backend.onrender.com';
  ```

## 5. Deploying so the real site can reach it

The backend needs to run on a server that stays on — a few free/cheap
options that work well for a small site like this:

- **Render** (render.com) — free web service tier, connects to a GitHub
  repo, auto-deploys on push. Set the environment variables from `.env` in
  its dashboard. Start command: `gunicorn app:app`
- **Railway** (railway.app) — similar to Render, generous free tier.
- **PythonAnywhere** — beginner-friendly, has a free tier, good if you'd
  rather not deal with Docker/build steps.
- **A small VPS** (e.g. a $4-6/mo droplet) — run with `gunicorn` behind
  nginx, use a process manager like `systemd` or `pm2` to keep it alive.

Whichever you choose, `requirements.txt` includes `gunicorn` for a proper
production server (don't use `python app.py`'s built-in dev server in
production — it says so itself when it starts).

Example production start command:
```bash
gunicorn -w 2 -b 0.0.0.0:$PORT app:app
```

Remember to set `ADMIN_EMAIL`, `ADMIN_PASSWORD`, and `JWT_SECRET` as real
environment variables on whichever host you use, rather than shipping your
`.env` file.

## API reference

All endpoints are under `/api`. Protected ones need a header:
`Authorization: Bearer <token>` (the token you get back from
`/api/auth/login`).

| Method | Path                  | Auth? | Notes                              |
|--------|-----------------------|-------|-------------------------------------|
| POST   | /api/auth/login       | no    | `{email, password}` → `{token}`     |
| GET    | /api/auth/me          | yes   | `{email}`                           |
| GET    | /api/projects         | no    | list                                |
| POST   | /api/projects         | yes   | `{tag, title, desc, img}`           |
| DELETE | /api/projects/:id     | yes   |                                      |
| GET    | /api/services         | no    | list                                |
| POST   | /api/services         | yes   | `{title, desc}`                     |
| DELETE | /api/services/:id     | yes   |                                      |
| POST   | /api/messages         | no    | contact form: `{name, email, message}` |
| GET    | /api/messages         | yes   | list, newest first                  |
| DELETE | /api/messages/:id     | yes   |                                      |
| GET    | /api/settings         | no    | site text/config                    |
| PUT    | /api/settings         | yes   | partial update, merges with existing |
| POST   | /api/pageview         | no    | `{path}` — fire-and-forget           |
| GET    | /api/stats            | yes   | `{views, messages, projects, services}` |

## Notes on what's simplified

- A single admin account (this is a personal portfolio, not a
  multi-user system). It's stored in the `admin_users` table so it's easy
  to extend later if you ever need more than one.
- Login has a light brute-force guard (6 failed attempts per IP+email locks
  that combination out for 5 minutes) — not a replacement for putting the
  admin route behind proper rate limiting if this ever gets more traffic.
- Uploaded project images are stored as base64 data URLs directly in the
  database, same as the old Firestore setup — fine at this scale, but if
  the project list grows a lot, moving to real file storage (disk or S3)
  would keep the database smaller.
