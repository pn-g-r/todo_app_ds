# Deploying the Todo App to Railway with PostgreSQL

This guide walks through every step to deploy this Django 6.0 todo app on Railway using PostgreSQL.

---

## Prerequisites

- Python 3.12 installed locally
- Git installed
- GitHub account
- Railway account (sign up at [railway.app](https://railway.app) — GitHub auth recommended)
- Project pushed to a GitHub repository

---

## Part 1: Local Project Changes

You need to make the following changes to your project **before** deploying.

### 1.1 Create `requirements.txt`

Create this file in the project root:

```
django>=6.0,<6.1
gunicorn
whitenoise
dj-database-url
psycopg[binary]
Pillow
```

**What each does:**
- `django` — the framework (pinned to 6.x)
- `gunicorn` — production WSGI server (Django's `runserver` is not for production)
- `whitenoise` — serves static files directly from the Django app
- `dj-database-url` — parses the `DATABASE_URL` environment variable Railway provides
- `psycopg[binary]` — PostgreSQL database adapter for Python (version 3, native async support)
- `Pillow` — image processing library (required by Django's `ImageField` for profile picture uploads)

---

### 1.2 Create `runtime.txt`

Create this file in the project root:

```
python-3.12.x
```

Railway reads this to know which Python version to install. `x` means "latest patch of 3.12".

---

### 1.3 Create `Procfile`

Create this file in the project root (no file extension):

```
web: python manage.py collectstatic --noinput && python manage.py migrate --noinput && gunicorn todoproject.wsgi --bind 0.0.0.0:${PORT} --log-file -
```

**What this does:**
- `web` — Railway runs this as the container's start command. It collects static files into `STATIC_ROOT` (needed for Whitenoise and Django admin styling), applies pending database migrations, then starts the application using gunicorn.
- `--bind 0.0.0.0:${PORT}` is **critical** — without it, Gunicorn binds to `127.0.0.1:8000` (loopback only). Railway's reverse proxy can't reach loopback inside the container, health checks fail, and the deploy is marked as crashed. `${PORT}` is the environment variable Railway injects dynamically at runtime.
- `collectstatic` is placed here (not in Railway's Pre-deploy Command) because Pre-deploy commands run in a **separate container** — any filesystem changes from Pre-deploy are lost. Static files must be collected in the same container that runs the web process.
- `migrate` with `--noinput` is harmless even if run on every container restart.
- If `collectstatic` fails, `migrate` and `gunicorn` are skipped — this lets you catch misconfigurations in the deploy logs.

> **Note:** Modern Railway uses **Railpack** which auto-detects Django projects and would configure `python manage.py migrate && gunicorn {app}.wsgi:application` automatically. The Procfile above overrides the auto-detected command to add `collectstatic`, which Railpack does not include by default.

---

### 1.4 Modify `todoproject/settings.py`

Open `todoproject/settings.py`. Make the following changes. **Why all of these?** The current `settings.py` is configured for local development only — hardcoded secrets, SQLite, debug mode on, no host restrictions. To run safely and correctly on Railway with PostgreSQL, every one of these settings must be made environment-aware and production-ready. Skipping any one of them will result in security vulnerabilities, crashes, or misrouted traffic.

#### a) Add `import os` at the top

After `from pathlib import Path`, add:

```python
import os
```

The top of the file should look like:

```python
from pathlib import Path
import os
```

**Why:** Django settings need to read environment variables for secrets and configuration. The `os` module is the standard Python way to access environment variables. Without `import os`, none of the `os.environ.get()` calls below will work — Python will raise a `NameError` at startup.

#### b) Change `SECRET_KEY` to use an environment variable

**Replace** this line:

```python
SECRET_KEY = "django-insecure-lpj*vla+g!a%=$g7j+h+^27yi(1b%n1!m@3k%w4^ahb$#+(4ez"
```

**With:**

```python
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
```

**Why:** The hardcoded `SECRET_KEY` is a security vulnerability — it's committed to Git and visible to anyone with access to the repository. In production, a leaked `SECRET_KEY` allows attackers to forge session cookies, CSRF tokens, and password reset tokens, effectively taking over user accounts. Moving it to an environment variable keeps the real secret out of version control. The fallback value is only used locally when no env var is set.

#### c) Change `DEBUG` to use an environment variable

**Replace:**

```python
DEBUG = True
```

**With:**

```python
DEBUG = os.environ.get("DEBUG", "False") == "True"
```

**Why:** `DEBUG=True` in production is a major security risk. Django's debug error pages expose your full source code, database queries, settings (including secret keys), and Python tracebacks to anyone who triggers an error. Attackers can use this information to find vulnerabilities. Additionally, `DEBUG=True` causes Django to cache all SQL queries in memory, eventually consuming all available RAM and crashing the server. The `"False"` default ensures production is always safe even if someone forgets to set the variable.

#### d) Change `ALLOWED_HOSTS` to use an environment variable

**Replace:**

```python
ALLOWED_HOSTS = []
```

**With:**

```python
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
```

**Why:** Django's `ALLOWED_HOSTS` is a security mechanism that prevents HTTP Host header attacks. An empty list `[]` means Django rejects all incoming requests (except from `localhost` in debug mode). In production, you must explicitly list every domain that's allowed to serve your app. If you forget to set this, every visitor will see a "Bad Request (400)" error. Using an environment variable lets you configure different domains for local dev (`localhost`) vs Railway (`yourapp.up.railway.app`) without changing code.

#### e) Add `CSRF_TRUSTED_ORIGINS`

Add this line **immediately after** `ALLOWED_HOSTS`:

```python
CSRF_TRUSTED_ORIGINS = [
    f"https://{host}" for host in ALLOWED_HOSTS
    if host not in ["127.0.0.1", "localhost"]
]
```

**Why:** Since Django 4.0, the CSRF middleware checks the `Origin` header on every HTTPS POST request. Railway forces HTTPS — so all form submissions (login, register, creating/editing/deleting todos, uploading profile pictures) go over HTTPS. Without `CSRF_TRUSTED_ORIGINS`, Django rejects all of them with a "403 Forbidden - CSRF verification failed" error. `ALLOWED_HOSTS` alone only validates the `Host` header, not the `Origin` — you need both.

This code auto-generates the trusted origins from `ALLOWED_HOSTS` by prefixing `https://` to each domain. It filters out `localhost`/`127.0.0.1` because local development typically runs over HTTP, not HTTPS — generating `https://localhost` would break CSRF checks on your dev machine.

#### f) Replace the `DATABASES` block

**Replace** the entire `DATABASES` block (lines 76-81):

```python
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}
```

**With:**

```python
import dj_database_url

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
        conn_health_checks=True,
    )
}
```

**What this does:**
- Reads `DATABASE_URL` from the environment (Railway injects this automatically when you add a PostgreSQL service).
- If `DATABASE_URL` is not set (local development), falls back to SQLite.
- `conn_max_age=600` keeps PostgreSQL connections alive for 10 minutes (reduces latency).
- `conn_health_checks=True` ensures stale connections are refreshed.

**Why this matters:** SQLite is a file-based database — it works fine locally but cannot be shared between multiple Railway containers and is lost on every redeploy (ephemeral filesystem). PostgreSQL is a proper network database server provisioned by Railway that persists data across deploys and can handle concurrent connections safely. `dj_database_url` bridges the two: it uses PostgreSQL when `DATABASE_URL` is present (production) and SQLite when it's not (local dev), so you never need to change code between environments.

**Important:** Move the `import dj_database_url` line to the top of the file, alongside the other imports (not inside the `DATABASES` block). The imports section should look like:

```python
from pathlib import Path
import os
import dj_database_url
```

#### g) Add `STATIC_ROOT` and configure Whitenoise

**Why this is needed:** Django's built-in `runserver` serves static files automatically during development. In production, Gunicorn does NOT serve static files — it only handles Python/WSGI requests. Without a static file server, Django admin CSS, JavaScript, and any custom static assets will return 404 errors, leaving the admin panel unstyled and unusable. Whitenoise fills this gap: it's a middleware that serves static files directly from the Django app without needing Nginx or a CDN. It's the simplest way to handle static files on Railway.

Add this line **after** `STATIC_URL` (around line 118):

```python
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
```

**Why `STATIC_ROOT`:** This is the directory where `collectstatic` gathers all static files from every installed app into one place. Whitenoise serves from this directory. Without it, `collectstatic` has nowhere to write.

Then add Whitenoise middleware to `MIDDLEWARE`. **Insert** this line right after `SecurityMiddleware`:

```python
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",   # <-- add this line
    "django.contrib.sessions.middleware.SessionMiddleware",
    ...
]
```

**Why right after `SecurityMiddleware`:** Whitenoise's docs require this position so it can intercept static file requests before Django's other middleware processes them. Putting it anywhere else causes Whitenoise to miss requests or behave unpredictably.

Finally, add Whitenoise storage backend at the end of the file:

```python
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
```

**Why `default` with `FileSystemStorage`:** Django 4.2+ reads ALL storage backends from the `STORAGES` setting. If you define `STORAGES` but omit `default`, Django doesn't fall back to the implicit default — it throws an error. Explicitly setting `default` to `FileSystemStorage` preserves the normal filesystem behavior for all file operations (including profile picture uploads locally). When Cloudinary is active, the `default` entry gets swapped for Cloudinary's backend.

**Why `CompressedManifestStaticFilesStorage`:** This storage backend compresses static files with gzip/Brotli and appends content-hashes to filenames (e.g., `styles.css` → `styles.a1b2c3d4.css`). The hashed names enable far-future cache headers, meaning browsers load your static files instantly on repeat visits. If you skip this and use the basic storage, Whitenoise still works but without compression or cache-busting.

#### h) Add `MEDIA_URL` and `MEDIA_ROOT`

Add these two lines **after** `STATIC_URL`:

```python
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))
```

**What this does:**
- `MEDIA_URL` — the URL prefix for serving user-uploaded files (profile pictures)
- `MEDIA_ROOT` — the filesystem directory where uploads are stored. In production on Railway, you will set the `MEDIA_ROOT` environment variable to match the volume mount path (see Section 2.5). Locally, it defaults to `media/` in the project root.
- The `Path(...)` wrapper ensures `MEDIA_ROOT` works correctly on all platforms

---

### 1.5 Create `.env.example`

**Why:** Your actual environment variables (secrets, API keys, database URLs) must never be committed to Git — that would expose them to everyone who accesses the repository. The `.env.example` file is a **template** that lists every variable the project needs without containing real values. Future developers (or you, 6 months from now) can copy it to `.env` and fill in the blanks. Without this file, required variables are easily forgotten, leading to confusing startup crashes.

Create `.env.example` in the project root as a reference for what environment variables are needed:

```
SECRET_KEY=generate-a-random-50-character-string-here
DEBUG=False
ALLOWED_HOSTS=yourapp.up.railway.app,your-custom-domain.com
DATABASE_URL=postgresql://user:password@host:5432/dbname
MEDIA_ROOT=/app/media
RAILWAY_RUN_UID=0
CLOUDINARY_URL=cloudinary://api_key:api_secret@cloud_name
```

**Do not commit `.env` files** — this is a template only. `MEDIA_ROOT` and `RAILWAY_RUN_UID` are only needed if using Railway Volumes (Approach A). `CLOUDINARY_URL` is only needed if using Cloudinary (Approach B).

---

### 1.6 Create `.gitignore` (if you don't have one)

**Why:** Git tracks every file in your repository unless told otherwise. Without a `.gitignore`, you risk committing sensitive files (`.env` with real secrets), build artifacts (`__pycache__/`, `staticfiles/`), local databases (`*.sqlite3`), and user-uploaded content (`media/`). Committing these causes several problems: secrets are leaked, your database file bloats the repository, and regenerated artifacts create endless merge conflicts. The `.gitignore` prevents all of this.

Make sure `.gitignore` includes at least:

```
__pycache__/
*.py[cod]
*.sqlite3
.env
staticfiles/
media/
```

---

### 1.7 Commit and push to GitHub

**Why:** Railway deploys from your GitHub repository. Every push to the connected branch triggers an automatic rebuild and deploy (this is Railway's "GitHub Autodeploys" feature). If you don't push, Railway has no code to deploy — the project will remain in its initial empty state. Additionally, you must commit the migration file (`todos/migrations/0002_profile.py`) so Railway can create the `Profile` table in PostgreSQL.

```bash
git add .
git commit -m "Prepare for Railway deployment"
git push
```

---

## Part 2: Railway Setup

### 2.1 Create a Railway Account

**Why:** Railway is the platform that will host your app and PostgreSQL database. Using GitHub sign-up links your GitHub account, which is required to connect your repository in the next step. Without this, you can't deploy from GitHub.

1. Go to [railway.app](https://railway.app)
2. Click **"Start a New Project"**
3. Sign up using your GitHub account (recommended — this makes repo connections seamless)

---

### 2.2 Create a New Project

**Why:** Each Railway "project" is an isolated environment containing one or more services (web app, database, etc.). Creating a project from your GitHub repo tells Railway: "watch this repository and deploy it whenever code changes." Without this connection, Railway has no code to run.

1. From the Railway dashboard, click **"+ New Project"**
2. Select **"Deploy from GitHub repo"**
3. If you haven't already, authorize Railway to access your GitHub repositories
4. Select the repository containing your todo project

Railway's **Railpack** build system automatically detects it's a Python project (via `requirements.txt` + `runtime.txt`) and configures the build process — installs Python 3.12, runs `pip install -r requirements.txt`, and prepares a container image. No manual build configuration needed.

---

### 2.3 Add PostgreSQL

**Why:** Your app currently uses SQLite — a file-based database that lives inside the container. Railway's containers are ephemeral: they're destroyed and recreated on every deploy, which would wipe all your todos and user accounts. PostgreSQL is a persistent database server that runs as a separate service on Railway. Your data survives any number of redeploys because it's stored outside the app container. PostgreSQL also handles multiple concurrent users safely — SQLite can't.

1. Inside your project, click **"+ New"** → **"Database"** → **"PostgreSQL"**
2. Railway provisions a PostgreSQL instance automatically
3. Railway **automatically injects** a `DATABASE_URL` environment variable into your service — you don't need to copy it manually

**How the connection works:** Your `settings.py` uses `dj_database_url.config()` which reads the `DATABASE_URL` env var that Railway just created. When your app starts, Django automatically connects to PostgreSQL instead of SQLite — zero manual configuration.

---

### 2.4 Set Environment Variables

**Why:** Every setting you made environment-aware in Part 1 (`SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `DATABASES`) now needs actual values in Railway. Without setting these variables here, Django will use the local fallback values — which means a hardcoded dev key, debug mode on, and no allowed hosts. The app would either be insecure or fail to start. Railway's Variables system stores these securely and injects them into your container at runtime.

1. In your project dashboard, click on your **web service** (not the database)
2. Go to the **"Variables"** tab
3. Add the following variables:

| Variable | Value | Notes |
|---|---|---|
| `SECRET_KEY` | A random 50-character string | Generate one at [djecrety.ir](https://djecrety.ir/) or use `python -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `DEBUG` | `False` | Must be `False` in production |
| `ALLOWED_HOSTS` | `yourapp.up.railway.app` | Replace with your actual Railway domain (you'll see it after the first deploy) |
| `MEDIA_ROOT` | `/app/media` | (Only if using Railway Volumes — Approach A) |
| `RAILWAY_RUN_UID` | `0` | (Only if using Railway Volumes — Approach A. Required for volume write permissions.) |
| `CLOUDINARY_URL` | `cloudinary://...` | (Only if using Cloudinary — Approach B) |

**Why each variable matters:**
- **`SECRET_KEY`** — Without this, Django uses the insecure hardcoded fallback. Anyone who can see your GitHub repo could forge session cookies and take over accounts.
- **`DEBUG`** — If omitted (=`"False"` by default), the app is secure. But setting it explicitly to `False` in Railway is a belt-and-suspenders practice — it prevents accidental debug-on deploys.
- **`ALLOWED_HOSTS`** — If this isn't set to your Railway domain, Django will reject every HTTP request with a 400 error. No-one can access your site.
- **`MEDIA_ROOT`** — Tells Django where the volume is mounted on the filesystem. If this doesn't match the volume mount path, uploads go to a different directory that gets wiped on redeploy.
- **`RAILWAY_RUN_UID`** — Without this, the container's non-root user can't write to the root-owned volume, causing silent upload failures.
- **`CLOUDINARY_URL`** — Tells Cloudinary's storage backend where to upload files. Without it, Django falls back to the local filesystem (which is ephemeral on Railway).

**Important notes:**
- `DATABASE_URL` is **already set** automatically by Railway when you added PostgreSQL — don't add it manually.
- The `SECRET_KEY` value above is just an example — generate your own unique key.

---

### 2.5 Persistent Storage for Uploaded Files

**Critical:** Railway's filesystem is **ephemeral** — every time your app redeploys or restarts, the container gets a fresh filesystem. Any user-uploaded files (profile pictures in `media/`) are **wiped out** on every deploy.

You need persistent storage so uploaded profile pictures survive redeploys. Two approaches below — pick one.

---

#### Approach A: Railway Volumes

**How it works:** You mount a persistent disk ("volume") into your service's container at the exact path where Django stores uploads. Files written to that directory survive redeploys. Zero additional services needed. Railway bills volumes per GB/minutely (see [Railway pricing](https://railway.com/pricing)). The **free plan** includes a single 0.5 GB volume — ample for profile pictures on a personal app.

> **Important caveats:** (1) Attaching a volume causes a brief downtime on every redeploy (Railway prevents two deployments from mounting the same volume simultaneously to avoid data corruption). (2) Each service can have only **one** volume. (3) Volumes are mounted as the `root` user — if your container runs as non-root, uploads will fail silently (see Step 2 below).

**Step 1 — Configure `urls.py` for production media serving**

Open `todos/urls.py`. The current `static()` helper is guarded by `if settings.DEBUG:`, which means media files are NOT served in production. For Railway Volumes, Django itself must serve the media files (since Railway runs Gunicorn directly, without Nginx).

**Replace:**

```python
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
```

**With:**

```python
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
```

> **Warning:** Django's `static()` view is designed for development, not production. For a small personal project this is acceptable. For anything with real traffic, use **Approach B (Cloudinary)** or put a CDN/CloudFront in front.

**Step 2 — Add required environment variables**

In Railway, go to your web service → **"Variables"** tab → add:

| Variable | Value | Notes |
|---|---|---|
| `MEDIA_ROOT` | `/app/media` | Must match the volume mount path |
| `RAILWAY_RUN_UID` | `0` | Ensures the container can write to the volume (volumes are mounted as root) |

Without `RAILWAY_RUN_UID=0`, file uploads to the volume may fail silently with a permission error.

**Step 3 — Attach a volume in Railway**

1. In your Railway project canvas, open the **Command Palette** (`⌘K` on Mac / `Ctrl+K` on Windows) — or right-click the canvas
2. Select **"Add Volume"**
3. Choose your **web service** when prompted to connect the volume
4. Configure the **Mount path:** `/app/media`
5. Click **"Deploy"** to apply

> **Note:** On Railway's free plan, volumes are limited to **0.5 GB** — more than enough for profile pictures. Each service can only have one volume.

**Step 4 — Verify**

1. After deploy, log into your app and upload a profile picture via the `/profile/` page
2. Trigger a redeploy (push to GitHub or click "Deploy" in Railway)
3. Visit the homepage — the profile picture should still be there

**Troubleshooting Approach A:**

| Problem | Likely cause |
|---|---|
| Profile pictures show 404 | `urls.py` still has the `if settings.DEBUG:` guard. Remove it. |
| Pictures gone after deploy | Volume mount path doesn't match `MEDIA_ROOT`. Double-check both are `/app/media`. |
| Upload silently fails (no error, no picture) | `RAILWAY_RUN_UID=0` is not set. The container can't write to the root-owned volume. |
| Upload fails with 500 | `Pillow` not installed — verify it's in `requirements.txt`. |
| Brief downtime on every deploy | Expected — Railway prevents two deployments from mounting the same volume simultaneously. |

---

#### Approach B: Cloudinary (Free Tier — 25 GB)

**How it works:** Instead of storing uploads on Railway's ephemeral disk, files are uploaded directly to Cloudinary's cloud storage. Cloudinary serves them via its CDN. No Railway Volumes needed. **Free tier:** 25 GB storage, 25 GB bandwidth/month, 1000 transformations/month — generous for a personal project.

**Step 1 — Add Cloudinary packages to `requirements.txt`**

**Why:** Cloudinary is a third-party service — it doesn't come with Django. `cloudinary` is the Python SDK for the Cloudinary API, and `django-cloudinary-storage` is the Django storage backend adapter that hooks into Django's file storage system. Without both packages, Django doesn't know how to talk to Cloudinary.

Add these two lines to `requirements.txt`:

```
cloudinary
django-cloudinary-storage
```

**Step 2 — Configure `todoproject/settings.py`**

**Why:** Django needs to know which storage backend to use for file uploads. By default, it uses the filesystem (`FileSystemStorage`). We need to conditionally swap it for Cloudinary's storage backend — but ONLY in production, so local development still uses the local filesystem. The conditional checks (`if CLOUDINARY_URL:`) ensure zero behavior change when Cloudinary is not configured.

**a)** Add `CLOUDINARY_URL` immediately after `SECRET_KEY` and before `INSTALLED_APPS`:

```python
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")

CLOUDINARY_URL = os.environ.get("CLOUDINARY_URL", "")
```

**b)** Modify the `INSTALLED_APPS` block to inject Cloudinary apps when the env var is set:

```python
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "todos",
]
if CLOUDINARY_URL:
    INSTALLED_APPS = ["cloudinary_storage", "cloudinary"] + INSTALLED_APPS
```

**c)** Update the `STORAGES` block (which you already added in Section 1.4f) to include media storage when Cloudinary is active:

```python
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
if CLOUDINARY_URL:
    STORAGES["default"] = {
        "BACKEND": "cloudinary_storage.storage.MediaCloudinaryStorage",
    }
```

**How this works:**
- When `CLOUDINARY_URL` is **set** (production on Railway) → uploads go to Cloudinary, served via Cloudinary CDN. Profile pictures survive any number of redeploys.
- When `CLOUDINARY_URL` is **not set** (local dev) → uploads go to the local `media/` folder as before, served by Django's dev server.
- No changes needed to `urls.py` — the `if settings.DEBUG:` guard stays, since media files are served by Cloudinary in production, not Django.

**Step 3 — Create a Cloudinary account**

**Why:** You need a Cloudinary account to get your API credentials — specifically the `CLOUDINARY_URL` string. This URL contains your cloud name, API key, and API secret, which authenticate your app to Cloudinary's servers. Without an account (and the URL), Cloudinary has no idea who's uploading files or where to store them.

1. Go to [cloudinary.com](https://cloudinary.com) → **Sign Up Free**
2. Complete registration (email or GitHub)
3. From the **Dashboard**, copy your **API Environment variable** — it looks like:
   ```
   cloudinary://123456789012345:abcdefGHIJKLMnopQRSTuvwxyz@dxxxxx
   ```

**Step 4 — Add `CLOUDINARY_URL` as a Railway environment variable**

**Why:** The `CLOUDINARY_URL` contains your API secret — it must never be hardcoded in settings.py or committed to Git. Railway's Variables system encrypts it and injects it into your container at runtime. Any Railway team member with access can see it, but it's never exposed in source code or build logs.

In Railway, go to your web service → **"Variables"** tab → add:

| Variable | Value | Notes |
|---|---|---|
| `CLOUDINARY_URL` | `cloudinary://...` | Paste the full URL from Cloudinary dashboard |

**Step 5 — Redeploy and verify**

**Why:** The `CLOUDINARY_URL` env var and the conditional `INSTALLED_APPS`/`STORAGES` changes only take effect after a new deploy. Until you redeploy, Django is still using the old settings. The verification step (inspecting the image URL in dev tools) is important because it confirms files are actually going to Cloudinary's CDN, not the local filesystem — a silent fallback to local storage would mean uploads are lost on the next deploy.

1. Redeploy your app
2. Log in and upload a profile picture via `/profile/`
3. Inspect the image URL in your browser dev tools — it should be a `res.cloudinary.com` URL
4. Trigger a redeploy — the picture persists because it's on Cloudinary, not Railway

**Troubleshooting Approach B:**

| Problem | Likely cause |
|---|---|
| Upload fails with "No module named cloudinary" | `cloudinary` or `django-cloudinary-storage` not in `requirements.txt`. Add them and redeploy. |
| Cloudinary images show 404 | `CLOUDINARY_URL` is missing or malformed. Double-check the Railway variable. |
| Images save locally instead of Cloudinary | `CLOUDINARY_URL` not being read before `INSTALLED_APPS`. Verify placement in settings.py. |

---

### 2.6 First Deploy

**Why:** This is the moment your code goes live. Railway's build process compiles your Python environment, runs your Procfile commands, and starts Gunicorn. Watching the logs here is critical — if any step fails (missing dependency, syntax error in settings.py, migration conflict), you'll see it in real time. Catching errors now avoids debugging a broken site later.

Railway should start deploying automatically when you push to GitHub. If not:

1. Go to your project dashboard
2. Click on your web service
3. Click **"Deploy"** (top right)
4. Watch the build logs — you should see:
   - `pip install -r requirements.txt` running
   - `python manage.py collectstatic --noinput` running
   - `python manage.py migrate --noinput` running
   - `gunicorn todoproject.wsgi` starting

---

### 2.7 Get Your Railway Domain

**Why:** Your app is running, but you need to know its public URL — and you must add it to `ALLOWED_HOSTS`. Django rejects requests from any domain not listed there, so even though the app is running, visitors will see "Bad Request (400)" until you whitelist the domain. Railway provides a free subdomain (`yourapp.up.railway.app`) — and you can also generate a custom one.

1. In your project dashboard, select your web service
2. Go to the **"Settings"** tab
3. Under **"Domains"**, you'll see your Railway-provided domain: `something.up.railway.app` — or click **"Generate Domain"** if none exists
4. Update your `ALLOWED_HOSTS` environment variable to include this domain if you haven't already
5. Click **"Deploy"** to apply the variable change

---

### 2.8 Run Migrations (Manual — if needed)

**Why:** Normally the `migrate` command in your Procfile handles this automatically. But migrations can fail silently in some edge cases — for example, if the database isn't fully provisioned when the start command runs, or if a migration conflicts with existing data. Running them manually here serves as a fallback to ensure your database schema matches your models. If you see "table does not exist" errors on the live site, this is the fix.

If migrations didn't run automatically (the Procfile's `web:` command runs `migrate` on every start, but if you skipped the Procfile entirely), run them manually:

**Option A — Railway Web Shell:**
1. Go to your web service → **"Shell"** tab
2. Run:
   ```bash
   python manage.py migrate
   ```

**Option B — Railway CLI (local):**
1. Install the Railway CLI: `npm i -g @railway/cli` (or `scoop install railway` on Windows)
2. Authenticate: `railway login`
3. Link your project: `railway link`
4. Run: `railway run python manage.py migrate`

---

### 2.9 Create a Superuser (Optional)

**Why:** Django's admin panel (`/admin/`) requires a staff/superuser account to log in. Without a superuser, you can't access the admin interface to manage users, todos, or profile data through the built-in GUI. Creating one here gives you a backdoor into your data — useful for debugging or manual data fixes. Note that the registration page on your app creates regular users (not superusers), so this is the only way to get admin access.

If you want to access Django admin (`/admin/`), create a superuser:

1. Open the Railway web shell (web service → **"Shell"** tab)
2. Run:
   ```bash
   python manage.py createsuperuser
   ```
3. Enter username, email, and password

---

### 2.10 Verify the Deployment

**Why:** A green deploy doesn't mean everything works. Static files might be broken (Whitenoise misconfiguration), the database might be unreachable (credentials issue), media uploads might fail silently (volume permissions), or CSRF/authentication might be broken (domain mismatch). Walking through every feature end-to-end catches these issues before real users encounter them. Each step below tests a specific subsystem.

1. Open your Railway domain in a browser
2. You should see the login page — **tests:** Whitenoise (CSS renders), Gunicorn (page loads), `ALLOWED_HOSTS` (no 400 error)
3. Register a new account and add a todo — **tests:** PostgreSQL connectivity, user creation, session auth, CSRF tokens
4. Check that login, logout, creating, editing, and deleting todos all function correctly — **tests:** full CRUD cycle, database writes, redirects
5. Go to `/profile/` and upload a profile picture — **tests:** `Pillow` is installed, `MEDIA_ROOT` is writable, file serving works
6. Confirm the picture appears (round) in the nav bar and on the homepage — **tests:** template rendering, media URL generation
7. Trigger a redeploy (push to GitHub) and confirm the profile picture is **still there** — **tests:** persistent storage is working (volume or Cloudinary), this is the ultimate validation

---

## Part 3: Custom Domain

**Why this matters:** Railway's default `*.up.railway.app` domain works perfectly, but it's not your brand. A custom domain (`todos.yourdomain.com`) looks professional, builds trust with users, and lets you control your URL if you ever migrate away from Railway. Railway makes this easy with automatic DNS and free Let's Encrypt SSL certificates.

### 3.1 Add a Custom Domain in Railway

**Why:** You need to tell Railway which domain you own and want to use. Railway then gives you a DNS target (CNAME) to point your domain at. Without this step, Railway doesn't know to accept traffic for your custom domain — requests would hit Railway but be rejected because no service is configured to handle them.

1. In your Railway project, go to your web service → **"Settings"** → **"Custom Domains"**
2. Click **"Add Domain"**
3. Enter your domain (e.g., `todos.yourdomain.com`)
4. Click **"Add"**

### 3.2 Configure DNS

**Why:** When someone types `todos.yourdomain.com` in their browser, the DNS system needs to know which server IP address handles that domain. A CNAME record says: "this subdomain is an alias for Railway's servers — go ask Railway's IP what to do." Without this DNS record, your domain won't resolve — visitors will see a "site can't be reached" error. The propagation delay (5-30 minutes) happens because DNS records are cached worldwide.

Railway will show you a **CNAME record value** (something like `yourproject.up.railway.app`).

1. Go to your domain registrar's DNS settings (Cloudflare, Namecheap, GoDaddy, etc.)
2. Add a **CNAME record**:
   - **Name:** `todos` (or whatever subdomain you chose)
   - **Target:** the CNAME value Railway provided
   - **TTL:** Auto or 3600
3. Save and wait for DNS propagation (usually 5-30 minutes)

### 3.3 Update ALLOWED_HOSTS

**Why:** Adding the domain in Railway tells Railway to route traffic for that domain to your service. But Django has its own independent security check — it verifies the `Host` header on every request and rejects anything not in `ALLOWED_HOSTS`. Both Railway AND Django must be configured, or you get a 400 error. This is Django's defense against HTTP Host header attacks.

1. Go to your web service → **"Variables"** tab
2. Edit `ALLOWED_HOSTS` and add your custom domain after the Railway domain:
   ```
   yourapp.up.railway.app,todos.yourdomain.com
   ```
3. Redeploy to apply

### 3.4 SSL Certificate

**Why:** Without SSL (HTTPS), all data between your users and your server is sent in plain text — passwords, session cookies, todo content. Anyone on the same network can intercept it. SSL encrypts the connection. Railway provisions Let's Encrypt certificates automatically — free, trusted by all browsers, and renewed before expiry. No manual configuration needed.

Railway automatically provisions a **Let's Encrypt SSL certificate** for your custom domain. No manual setup needed — it can take up to 10 minutes after DNS propagates.

---

## Appendix: Full `settings.py` After Changes

For reference, here is what `todoproject/settings.py` should look like after all modifications:

```python
from pathlib import Path
import os
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")

CLOUDINARY_URL = os.environ.get("CLOUDINARY_URL", "")

DEBUG = os.environ.get("DEBUG", "False") == "True"

ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")

CSRF_TRUSTED_ORIGINS = [
    f"https://{host}" for host in ALLOWED_HOSTS
    if host not in ["127.0.0.1", "localhost"]
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "todos",
]
if CLOUDINARY_URL:
    INSTALLED_APPS = ["cloudinary_storage", "cloudinary"] + INSTALLED_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "todoproject.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "todoproject.wsgi.application"

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
        conn_health_checks=True,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
if CLOUDINARY_URL:
    STORAGES["default"] = {
        "BACKEND": "cloudinary_storage.storage.MediaCloudinaryStorage",
    }

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "todo_list"
LOGOUT_REDIRECT_URL = "login"
```

---

## Troubleshooting

| Problem | Solution |
|---|---|
| **"Bad Request (400)"** when accessing the site | `ALLOWED_HOSTS` doesn't include the domain you're using. Update the env var in Railway and redeploy. |
| **"DisallowedHost" error** | Same as above — add the exact domain to `ALLOWED_HOSTS`. |
| **Database errors on first load** | Migrations may not have run. Run `python manage.py migrate` via the Railway shell. |
| **Static files not loading (CSS/images broken)** | `collectstatic` may not have run. Run `python manage.py collectstatic --noinput` via Railway shell, then redeploy. |
| **Profile picture disappears after redeploy** | Persistent storage is not configured. Set up Railway Volumes or Cloudinary — see Section 2.5. |
| **"Upload a valid image" error on profile page** | `Pillow` is not installed. Add it to `requirements.txt` and redeploy. |
| **Profile pictures show 404 in production** | For Approach A: the `if settings.DEBUG:` guard in `urls.py` blocks media serving. Remove the guard. For Approach B: verify `CLOUDINARY_URL` is set correctly. |
| **Cloudinary upload fails with import error** | `cloudinary` or `django-cloudinary-storage` not installed. Check `requirements.txt`. |
| **Application error / crash loop** | Check Railway build logs. Common causes: missing env vars, `psycopg2` not installed, or a syntax error in settings. |
| **502 Bad Gateway** | Gunicorn may be failing. Check Railway logs. Often caused by `collectstatic` not running (Whitenoise can't find the manifest file). Run it manually via Railway Shell. |
| **Profile picture upload silently fails** | If using volumes, `RAILWAY_RUN_UID=0` may be missing. The container can't write to the root-owned volume mount. |
| **"Permission denied" writing to media/** | Same as above — add `RAILWAY_RUN_UID=0` to Railway Variables. |

---

## Summary of File Checklist

Before pushing to GitHub, make sure these files exist/are modified:

- [ ] `requirements.txt` (new — includes `Pillow`, and optionally `cloudinary`/`django-cloudinary-storage`)
- [ ] `runtime.txt` (new)
- [ ] `Procfile` (new — single `web:` command: `collectstatic && migrate && gunicorn`)
- [ ] `todoproject/settings.py` (modified — 8 changes: `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `DATABASES`, `STATIC_ROOT`+Whitenoise, `MEDIA_URL`/`MEDIA_ROOT`, `CLOUDINARY_URL`+conditional blocks)
- [ ] `todos/urls.py` (modified — remove `if settings.DEBUG:` guard if using Approach A)
- [ ] `.env.example` (new)
- [ ] `.gitignore` (updated — add `staticfiles/`, `media/`, and `.env`)
