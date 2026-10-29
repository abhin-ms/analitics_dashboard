# BP Analytics — CRM & Live Ops Dashboard for BreakProtection

Production-grade CRM and live analytics dashboard for BreakProtection's 24 stores across India.

## Tech Stack

- **Backend**: FastAPI, SQLAlchemy 2.0, Alembic, Pydantic v2, JWT auth
- **Database**: MySQL 8 / MariaDB 10.x (XAMPP for local dev)
- **Frontend**: React 18, Vite, TypeScript, Tailwind CSS, Recharts, TanStack Query, Zustand
- **Sync**: Google Sheets API v4 (stubbed until credentials provided)

## Prerequisites

- Python 3.11+
- Node.js 18+
- MariaDB/MySQL (via XAMPP or native install)

## Quick Start on Windows (day-to-day)

Once the first-time setup below is done, this is all you need. Use two PowerShell windows.

**Window 1: backend** (http://localhost:8000)

```powershell
cd backend
.venv\Scripts\activate
alembic upgrade head          # apply any new database changes (safe to run every time)
uvicorn app.main:socket_app --reload --port 8000
```

**Window 2: frontend** (http://localhost:5173)

```powershell
cd frontend
npm install                   # only after package.json changes
npm run dev
```

Open http://localhost:5173 and log in. Make sure MySQL/MariaDB (XAMPP) is running first.

- **Settings** live in `backend/.env` (database URL, keys). Never commit this file.
- **Real data locally:** instead of the seed script, import a dump of the live database into
  `bp_analytics`, e.g. `mysql -u root -p bp_analytics < live_dump.sql`, then run `alembic upgrade head`.
  Background jobs (sheet sync every minute, automation, 1 PM and 8 PM CEO report) also run locally.
  WhatsApp settings come from the database, so a live copy can send real messages: switch WhatsApp
  off locally in Settings → WhatsApp before testing.
- **Tests:** `cd backend` then `.venv\Scripts\python -m pytest -q`. One test
  (`test_symlink_out_of_the_build_is_refused`) always fails on Windows and can be ignored.
  Frontend check: `cd frontend` then `npx tsc --noEmit -p .`
- **Going live:** push your branch and open a pull request to `main`; merging to `main` deploys.

## Local Setup

### 1. Database

Start XAMPP MariaDB, then create the database:

```sql
CREATE DATABASE bp_analytics CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### 2. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env
# Edit .env with your database credentials
```

### 3. Seed Data

```bash
python scripts/seed.py
```

This creates:
- 9 roles (SuperAdmin, Admin, CEO, COO, Regional Manager, Team Leader, Store Staff, Telecaller, Salesperson, Viewer)
- 90 permissions (15 resources x 6 actions)
- SuperAdmin account: `admin@breakprotection.com` / `admin123`
- COO account: `coo@breakprotection.com` / `coo123`
- 11 Team Leaders (6 original + 5 city-based) with store access
- 5 Salespersons (1 per city-based TL)
- 5 Telecallers (tele call team)
- 29 stores (24 original + 5 city-based)
- 5 currencies (INR, USD, GBP, AED, EUR)
- 10 KPI weights (summing to 1.00)
- 4 incentive bands (with Below Target placeholder)

### 4. Run Backend

```bash
uvicorn app.main:socket_app --reload --host 0.0.0.0 --port 8000
```

### 5. Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at http://localhost:5173, proxies API calls to localhost:8000.

## Running Tests

```bash
cd backend
python -m pytest tests/ -v
```

32 tests covering:
- KPI scoring engine (band resolution, weighted scores)
- Currency formatting (INR Lakh/Crore, Western K/M/B)
- Currency conversion logic
- Password hashing (bcrypt)
- JWT token creation/verification
- Permission checking logic

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | Async MySQL connection string | `mysql+aiomysql://root:password@localhost:3306/bp_analytics` |
| `JWT_SECRET_KEY` | Secret for JWT signing | `change-me-to-a-random-secret` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT access token TTL | `15` |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Refresh token cookie TTL | `7` |
| `GOOGLE_SERVICE_ACCOUNT_JSON_PATH` | Path to service account JSON | Empty (sync no-ops) |
| `CORS_ORIGINS` | Comma-separated allowed origins | `http://localhost:5173` |
| `BASE_REPORTING_CURRENCY` | Company-wide rollup currency | `INR` |
| `SMARTSERVICE_MCP_URL` | SmartService MCP endpoint | `https://smartserviceapitemp.azurewebsites.net/mcp` |
| `DEFAULT_TIMEZONE` | Server timezone | `Asia/Kolkata` |

## API Endpoints

### Auth
- `POST /api/v1/auth/login` — Login (returns JWT + refresh cookie)
- `POST /api/v1/auth/refresh` — Refresh access token
- `GET /api/v1/auth/me` — Current user + permissions
- `POST /api/v1/auth/logout` — Clear refresh cookie
- `POST /api/v1/auth/forgot-password` — Generate reset token
- `POST /api/v1/auth/set-password` — Set password via token

### Resources (CRUD)
- `/api/v1/stores` — Store management
- `/api/v1/submissions` — Daily submissions
- `/api/v1/leads` — Lead management + activities + lost reasons
- `/api/v1/campaigns` — Campaign management
- `/api/v1/tasks` — Task management
- `/api/v1/investments` — Investment tracking
- `/api/v1/users` — User management
- `/api/v1/roles` — Role + permission matrix
- `/api/v1/performance/scores` — KPI scores + incentive bands
- `/api/v1/reports/*` — Monthly summary, leaderboard, lost reasons, CSV export
- `/api/v1/dashboard` — CEO dashboard (KPIs, charts, trends)
- `/api/v1/currencies` — Currency + exchange rate management
- `/api/v1/sync/*` — Google Sheets sync (stubbed)
- `/api/v1/settings/*` — KPI weights, incentive bands, app settings

## Roles & Permissions

| Role | Dashboard | Stores | Operations | Leads | Tasks | Performance | Reports | Admin |
|---|---|---|---|---|---|---|---|---|
| SuperAdmin | Full | Full | Full | Full | Full | Full | Full | Full |
| Admin | Full | Full | Full | Full | Full | Full | Full | Full |
| CEO | View | View | View | View | View | View+Export | View | - |
| COO | View | View+Edit | View | View | View | View+Export | View | - |
| Regional Manager | View | View+Edit | View+Edit | View+Edit | View+Edit | View | View | - |
| Team Leader | View | View | View+Edit | Create+Edit | Create+Edit | View | View | - |
| Store Staff | View | View | Create | Create | View | - | - | - |
| **Telecaller** | View | - | View | Create+Edit | - | - | - | - |
| **Salesperson** | View | - | Create | Create+Edit | Create | - | - | - |
| Viewer | View | View | View | View | View | View | View | - |

## Login Credentials

### Admin & Management

| Role | Name | Email | Password |
|------|------|-------|----------|
| SuperAdmin | SuperAdmin | `admin@breakprotection.com` | `admin123` |
| COO | COO | `coo@breakprotection.com` | `coo123` |

### Team Leaders (Original)

| Role | Name | Email | Password | Stores |
|------|------|-------|----------|--------|
| Team Leader | Harsh | `breakprotectiontele@gmail.com` | `harsh123` | Kerala Kochi, Kerala Calicut, Kerala Kottkal, Kerala Wayanad |
| Team Leader | Sam | `breakprotectionkodchennai@gmail.com` | `sam123` | Kerala Trivandrum, Chennai Kodambakam, Chennai Velachery, Tn Coimbatore, Kerala Kollam |
| Team Leader | Michael | `michael.breakprotection@gmail.com` | `michael123` | Kerala Thrissur, Kerala Kannur, Kerala Palakkad, Guwahati, Kerala Pathanamthitta, Kerala Kasargod |
| Team Leader | Vishnu | `breakprotectionmarathahalli@gmail.com` | `vishnu123` | Bangalore Marathahalli, Mangalore, Mysore |
| Team Leader | Abdullah | `breakprotectionhytech@gmail.com` | `abdullah123` | Mumbai Korum, Mumbai Bandra, Delhi Lajpat Nagar, Hyderabad Kukatpally, Hyderabad Hitech |
| Team Leader | Nazil | `breakprotectionindiranagar@gmail.com` | `nazil123` | Bangalore Indiranagar |

### Team Leaders (City-Based)

| Role | Name | Email | Password | Store |
|------|------|-------|----------|-------|
| Team Leader | Guwahati | `guwahati@breakprotection.com` | `guwahati123` | Guwahati Store |
| Team Leader | Delhi | `delhi@breakprotection.com` | `delhi123` | Delhi Store |
| Team Leader | Kerala | `kerala@breakprotection.com` | `kerala123` | Kerala Store |
| Team Leader | Chennai | `chennai@breakprotection.com` | `chennai123` | Chennai Store |
| Team Leader | Mumbai | `mumbai@breakprotection.com` | `mumbai123` | Mumbai Store |

### Salespersons

| Role | Name | Email | Password | TL Under |
|------|------|-------|----------|----------|
| Salesperson | Ravi | `ravi@breakprotection.com` | `ravi123` | Guwahati |
| Salesperson | Amit | `amit@breakprotection.com` | `amit123` | Delhi |
| Salesperson | Priya | `priya@breakprotection.com` | `priya123` | Kerala |
| Salesperson | Deepak | `deepak@breakprotection.com` | `deepak123` | Chennai |
| Salesperson | Rohit | `rohit@breakprotection.com` | `rohit123` | Mumbai |

### Telecallers

| Role | Name | Email | Password |
|------|------|-------|----------|
| Telecaller | SANJAY | `sanjay@breakprotection.com` | `sanjay123` |
| Telecaller | Nazil Tele | `nazil.tele@breakprotection.com` | `nazil123` |
| Telecaller | Nirmala | `nirmala@breakprotection.com` | `nirmala123` |
| Telecaller | SAM Tele | `sam.tele@breakprotection.com` | `sam123` |
| Telecaller | Ekbal | `ekbal@breakprotection.com` | `ekbal123` |

### Creating Additional Users

Admins can create more Team Leaders and Salespersons via **Settings > Users** in the dashboard. The admin account has full `users:create` permission.

## Google Sheets Sync

### Setup (requires Abhin)

1. Create a Google Cloud project with Sheets API + Drive API enabled
2. Create a service account, download the JSON key
3. Set `GOOGLE_SERVICE_ACCOUNT_JSON_PATH` in `.env`
4. Share each Google Sheet with the service account email as Viewer
5. Add sheet sources via Settings > Data Sync or the API

### Adding a New Sheet Source

```bash
curl -X POST http://localhost:8000/api/v1/sync/sources \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"label": "Daily Ops", "spreadsheet_id": "...", "tab_mappings": {...}}'
```

## Open Items (Section 0)

- [ ] Below Target incentive band values (placeholder: min=0, multiplier=1.0)
- [ ] Care+ Attachment Rate weight (currently 0.00 — confirm intentional)
- [ ] Google Sheets tab names and headers for all 3 sources
- [ ] Sheet #3: native Sheet or uploaded .xlsx?
- [ ] SmartService MCP API key
- [ ] Email sending scope for invite/reset flow
