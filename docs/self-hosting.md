# Self-Hosting Guide

FileMorph is designed to be self-hosted. This guide covers production deployments with Docker,
reverse proxy setup (nginx), HTTPS/SSL, and operational best practices.

---

## Why self-host?

- **Data privacy (DSGVO / GDPR)**: Files never leave your own infrastructure
- **No rate limits**: Control throughput yourself
- **Custom access**: Issue API keys to your own users or services
- **Integration**: Run FileMorph inside your existing network, accessible only to internal services

---

## Production setup with Docker

### 1. Clone and configure

```bash
git clone https://github.com/MrChengLen/FileMorph.git
cd filemorph
cp .env.example .env
```

Edit `.env` for production:

```env
APP_HOST=0.0.0.0
APP_PORT=8000
APP_DEBUG=false
APP_VERSION=1.0.0

API_KEYS_FILE=data/api_keys.json

MAX_UPLOAD_SIZE_MB=100

# Restrict to your own domain in production
CORS_ORIGINS=https://yourapp.example.com,https://portal.example.com

# Optional: route heavy upload POSTs (convert/compress, single + batch) through
# a separate subdomain. Empty string = same-origin (default, simplest). Set
# only when the main site sits behind a proxy that caps request bodies and
# uploads must bypass it via a tunnel subdomain. The browser then cross-origins
# those POSTs to the listed URL; `CORS_ORIGINS` must include the main site
# origin so the preflight passes. Format-list GET + auth stay same-origin.
API_BASE_URL=
```

### 2. Start the container

```bash
docker compose up -d
```

### 3. Generate API keys

```bash
docker compose exec filemorph python scripts/generate_api_key.py
```

The key is stored as a hash in `./data/api_keys.json` (bind-mounted into the container).

### 4. Verify

```bash
curl http://localhost:8000/api/v1/health
```

---

## Reverse proxy with nginx (HTTPS)

Place FileMorph behind nginx to handle SSL termination and domain routing.

### nginx configuration

```nginx
# /etc/nginx/sites-available/filemorph

server {
    listen 80;
    server_name filemorph.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name filemorph.example.com;

    ssl_certificate     /etc/letsencrypt/live/filemorph.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/filemorph.example.com/privkey.pem;

    # Increase for large file uploads
    client_max_body_size 200M;

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;

        # Increase timeouts for large file conversions
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
}
```

Enable and reload:
```bash
sudo ln -s /etc/nginx/sites-available/filemorph /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### Free SSL certificate with Certbot

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d filemorph.example.com
```

Certbot automatically renews certificates every 90 days.

---

## Restrict to internal network only

If FileMorph should only be accessible within your organization (no public internet):

**Option A — Bind to internal IP only**

In `.env`:
```env
APP_HOST=192.168.1.50    # your server's internal IP
```

**Option B — Use a firewall**

```bash
# Allow only internal subnet
sudo ufw allow from 192.168.1.0/24 to any port 8000
sudo ufw deny 8000
```

**Option C — Docker network only** (FileMorph as a microservice)

```yaml
# docker-compose.yml — no port exposed externally
services:
  filemorph:
    build: .
    expose:
      - "8000"          # accessible only within Docker network
    networks:
      - internal

  your-app:
    image: your-app
    networks:
      - internal

networks:
  internal:
    driver: bridge
```

Your application calls FileMorph at `http://filemorph:8000` (Docker service name).

---

## API Key management

### Generate a new key

```bash
docker compose exec filemorph python scripts/generate_api_key.py
```

### Revoke a key

Keys are stored as SHA-256 hashes in `data/api_keys.json`:

```json
{
  "keys": [
    "abc123hash...",
    "def456hash..."
  ]
}
```

To revoke, delete the corresponding hash entry and save the file.
No restart required — keys are re-read on every request.

### Rotate a key

1. Generate a new key: `python scripts/generate_api_key.py`
2. Update your application/service with the new key
3. Remove the old hash from `data/api_keys.json`

---

## Operational notes

### Automatic restart

Docker Compose is configured with `restart: unless-stopped` — FileMorph restarts automatically after a server reboot or crash.

Enable your Docker daemon to start on boot:
```bash
sudo systemctl enable docker
```

### Health monitoring

The health endpoint is designed for monitoring tools and load balancers:

```
GET /api/v1/health
```

Example with **uptime monitoring** (e.g. UptimeRobot, Gatus):
- URL: `https://filemorph.example.com/api/v1/health`
- Expected keyword: `"status":"ok"`

### Log access

```bash
docker compose logs -f filemorph
```

### Disk space

All file processing happens in temporary directories that are cleaned up automatically after each request. FileMorph does not store uploaded or converted files permanently.

The only persistent data is `data/api_keys.json`.

### Updating

```bash
git pull
docker compose build --no-cache
docker compose up -d
```

API keys in `./data/` are preserved across updates.

---

## systemd service (without Docker)

For running FileMorph directly as a Linux service:

```ini
# /etc/systemd/system/filemorph.service

[Unit]
Description=FileMorph file conversion service
After=network.target

[Service]
Type=simple
User=filemorph
WorkingDirectory=/opt/filemorph
Environment="PATH=/opt/filemorph/.venv/bin"
ExecStart=/opt/filemorph/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now filemorph
sudo systemctl status filemorph
```

---

## Security checklist

- [ ] Set `CORS_ORIGINS` to your specific domain(s), not `*`
- [ ] Set `APP_DEBUG=false` in production
- [ ] Keep `data/api_keys.json` out of version control (it is in `.gitignore`)
- [ ] Use HTTPS (see nginx + Certbot above)
- [ ] Set `MAX_UPLOAD_SIZE_MB` to a sensible limit for your use case
- [ ] Restrict network access if the service is internal-only
- [ ] Rotate API keys regularly
- [ ] Monitor disk usage (temp files are cleaned up, but check `/tmp` if issues occur)
