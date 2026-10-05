# Deployment — dash.breakprotection.com

The server (187.127.216.149, Ubuntu 24.04) is managed with **aaPanel**. aaPanel's nginx owns ports 80 and 443 for every site on the box, and it already holds the HTTPS certificate for `dash.breakprotection.com`. This app runs in Docker **behind** that nginx.

```
browser ──https──> aaPanel nginx (SSL) ──> 127.0.0.1:8010 ──> app container ──> db container (MariaDB 10.11)
```

Every push to `main` runs `.github/workflows/deploy.yml`:

1. **test**: type-checks and builds the frontend, then runs the backend tests (Python 3.12).
2. **build-and-push**: builds one image (React build plus FastAPI) and pushes it to `ghcr.io/<owner>/<repo>:<commit>`.
3. **deploy**: copies `docker-compose.yml` to `/opt/bp-analytics`, writes the config from GitHub secrets, runs **`alembic upgrade head`**, restarts the containers, and checks `http://127.0.0.1:8010/health`.

Pull requests only run **test**.

Containers (`docker-compose.yml`):

| Service | What it is |
|---|---|
| `db` | MariaDB 10.11. Data is in the `db_data` volume and is never published outside Docker. |
| `app` | The dashboard, on `127.0.0.1:8010` only. It runs the sheet and MCP sync scheduler, so **exactly one copy** must run. |
| `backup` | A gzipped dump into `/opt/bp-analytics/backups` every day, keeping the last 14 days. |

---

## A. One-time server setup (as root on the server)

```bash
docker compose version          # must print v2.x (Docker is already installed)

adduser --disabled-password --gecos "" deploy
usermod -aG docker deploy
mkdir -p /opt/bp-analytics && chown deploy:deploy /opt/bp-analytics
```

Create a key that GitHub Actions uses to log in. Run this **on your laptop**:
```bash
ssh-keygen -t ed25519 -f ~/.ssh/bp_deploy_key -N "" -C "github-actions-deploy"
cat ~/.ssh/bp_deploy_key.pub          # copy this one line
```
Then authorise it **on the server**. Paste the line you just copied in place of `PASTE_PUBLIC_KEY_HERE`:
```bash
mkdir -p /home/deploy/.ssh
echo "PASTE_PUBLIC_KEY_HERE" >> /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy/.ssh && chmod 700 /home/deploy/.ssh && chmod 600 /home/deploy/.ssh/authorized_keys
```
Test it from your laptop: `ssh -i ~/.ssh/bp_deploy_key deploy@187.127.216.149 docker ps` should list containers.

## B. GitHub secrets

In the repo, go to **Settings → Environments → New environment → `production`**, then add these secrets under **Environment secrets**:

| Secret | Value |
|---|---|
| `SERVER_HOST` | `187.127.216.149` |
| `SERVER_USER` | `deploy` |
| `SERVER_SSH_KEY` | the whole private key: `cat ~/.ssh/bp_deploy_key` on your laptop |
| `DB_ROOT_PASSWORD` | new: run `openssl rand -hex 24` |
| `DB_PASSWORD` | new: run `openssl rand -hex 24` again (letters and digits only) |
| `APP_ENV` | the whole live settings file. On the server, run `cat /www/wwwroot/dash.breakprotection.com/backend/.env` and paste all of it |
| `GOOGLE_SA_JSON` | on the server, run `cat /www/wwwroot/dash.breakprotection.com/backend/bp-analytics-sync-75ca3b0a13a4.json` and paste all of it |

Pasting the live `.env` as-is is intended. It keeps the same `TOKEN_ENCRYPTION_KEY`, JWT secret, MCP, SMTP and Meta settings. The values that must differ in Docker (`DATABASE_URL`, `CORS_ORIGINS`, `FRONTEND_URL`, `SECURE_COOKIES`, the Google key path) are overridden by `docker-compose.yml`.

## C. First push

Push to `main`. **test** and **build-and-push** should go green. **deploy** then starts the new empty database and **stops on purpose** with *"Database is empty"*.

Nothing has touched the live site yet: aaPanel still serves the old app on port 8000.

## D. Cut-over (≈10 minutes; do it at a quiet time)

Run everything **as root on the server**.

**1. Stop the old app**, so no new leads are written to the old database. In aaPanel, go to **App Store → Supervisor → stop the dash.breakprotection.com process**. The site now shows a 502 until step 5.

**2. Dump the live database** using the old app's own credentials:
```bash
eval "$(grep '^DATABASE_URL' /www/wwwroot/dash.breakprotection.com/backend/.env | python3 -c "
import sys, urllib.parse as u, shlex
p = u.urlparse(sys.stdin.read().split('=', 1)[1].strip().replace('mysql+aiomysql', 'mysql'))
print(f'DBU={shlex.quote(p.username)}; DBP={shlex.quote(u.unquote(p.password))}')")"
mysqldump -h 127.0.0.1 -u "$DBU" -p"$DBP" --single-transaction --no-tablespaces bp_analytics | gzip > /root/bp_analytics_cutover.sql.gz
ls -lh /root/bp_analytics_cutover.sql.gz        # should be well over a few KB
```

**3. Import it into the new database:**
```bash
cd /opt/bp-analytics
gunzip -c /root/bp_analytics_cutover.sql.gz | docker compose exec -T db sh -c 'mariadb -u root -p"$MARIADB_ROOT_PASSWORD" bp_analytics'
```

**4. Start the new app.** In GitHub, go to **Actions → Deploy → Run workflow** (on `main`). It migrates, starts the app and prints `app healthy on 127.0.0.1:8010`. Check it yourself too: `curl -s http://127.0.0.1:8010/health` should print `{"status":"ok"}`.

**5. Point the site at the new app:**
```bash
C=/www/server/panel/vhost/nginx/dash.breakprotection.com.conf
cp "$C" /root/dash.breakprotection.com.conf.before-docker
sed -i 's#http://127.0.0.1:8000#http://127.0.0.1:8010#g' "$C"
grep -n proxy_pass "$C"                       # both lines should now say 8010
/www/server/nginx/sbin/nginx -t && /www/server/nginx/sbin/nginx -s reload
```

**6. Check** https://dash.breakprotection.com: log in, open the dashboard and Social Performance, and confirm a new lead alert arrives.

**7. Keep the old app off.** In aaPanel → Supervisor, disable autostart for the old process. Keep `/www/wwwroot/dash.breakprotection.com` for a week as a fallback, then remove the site.

### Rollback (if step 6 fails)
```bash
cp /root/dash.breakprotection.com.conf.before-docker /www/server/panel/vhost/nginx/dash.breakprotection.com.conf
/www/server/nginx/sbin/nginx -s reload
```
Then start the old app again in aaPanel → Supervisor. Data entered in the new app after the cut-over is not in the old database, so roll back early if you're going to.

---

## Day to day

```bash
cd /opt/bp-analytics
docker compose ps                  # status of db / app / backup
docker compose logs -f app         # live backend logs (syncs, errors)
docker compose logs backup         # backup results
```

- **Deploy:** push to `main`. Migrations run automatically.
- **Change a setting:** update the `APP_ENV` (or another) secret, then run **Actions → Deploy → Run workflow**. `.env`, `app.env` and the Google key on the server are rewritten on every deploy.
- **Roll back to an earlier build:** set `APP_IMAGE=ghcr.io/<owner>/<repo>:<older-commit-sha>` in `/opt/bp-analytics/.env`, then run `docker compose up -d app`.
- **Restore a backup:**
  ```bash
  gunzip -c backups/bp_analytics_YYYY-MM-DD_HHMM.sql.gz | docker compose exec -T db sh -c 'mariadb -u root -p"$MARIADB_ROOT_PASSWORD" bp_analytics'
  ```
  Copy `backups/` off the server regularly.
