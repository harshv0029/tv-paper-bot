# TradingView → Paper Trading Bot

A tiny webhook receiver that logs simulated trades from TradingView alerts.
No real orders are placed — this is Phase 2 of the paper-trading roadmap:
validate the automation *pipeline* (alert → signal → logged trade) before any
broker is involved.

Files:
- `main.py` — the FastAPI app (webhook receiver + position/P&L tracking)
- `requirements.txt` — Python dependencies
- `Procfile` — tells Render/Heroku-style hosts how to start it

---

## 1. Deploy it somewhere public

TradingView's servers need to reach your app over the public internet, over
**HTTPS** — TradingView will not send webhooks to plain HTTP or to
`localhost`. This workspace can't host that itself, so put it on a host you
control. Two paths:

### 1a. Managed platform (Render, free tier — quickest to get running)

1. Create a GitHub repo and push these 4 files to it (or use Render's "deploy
   from a folder" flow if you don't want GitHub).
2. Go to https://render.com → New → Web Service → connect the repo.
3. Settings:
   - Runtime: Python 3
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Add an environment variable **`WEBHOOK_SECRET`** — pick a long random
   string (e.g. `openssl rand -hex 20`). This is what stops random people
   from posting fake trades to your endpoint.
5. Deploy. Render gives you a free HTTPS URL like `https://your-app.onrender.com`.
6. Test it's alive: `curl https://your-app.onrender.com/health`

(Render's free tier sleeps after inactivity and takes a few seconds to wake
on the next request — fine for paper trading, not for low-latency live
trading later.)

### 1b. Your own VPS (DigitalOcean, Hetzner, Linode, AWS Lightsail, etc.)

More control, and this is closer to what you'll run for live trading later
(you'll also need a fixed/static IP for the broker API step — see Phase 4 of
the roadmap — so getting comfortable with a real VPS now isn't wasted effort).
Assuming a fresh Ubuntu/Debian box:

1. **Point a domain at it.** Buy/use a domain (or a free subdomain) and add
   an A record pointing to the VPS's IP. You need this because Let's
   Encrypt (the free HTTPS cert) won't issue a certificate for a bare IP,
   and TradingView requires HTTPS.

2. **Install prerequisites:**
   ```bash
   sudo apt update && sudo apt install -y python3-pip python3-venv nginx certbot python3-certbot-nginx
   ```

3. **Copy the files over** (scp, git clone, or rsync) into e.g. `~/tv-paper-bot`
   on the server, then:
   ```bash
   cd ~/tv-paper-bot
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

4. **Run it as a systemd service** so it survives reboots and SSH
   disconnects. Create `/etc/systemd/system/tv-paper-bot.service`:
   ```ini
   [Unit]
   Description=TradingView Paper Trading Bot
   After=network.target

   [Service]
   User=YOUR_LINUX_USER
   WorkingDirectory=/home/YOUR_LINUX_USER/tv-paper-bot
   Environment="WEBHOOK_SECRET=your-long-random-secret"
   ExecStart=/home/YOUR_LINUX_USER/tv-paper-bot/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```
   Then:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now tv-paper-bot
   sudo systemctl status tv-paper-bot   # confirm it's running
   ```

5. **Put nginx in front of it and get HTTPS**, so the app itself only ever
   listens on localhost (safer) and nginx handles TLS:
   ```bash
   sudo tee /etc/nginx/sites-available/tv-paper-bot <<'EOF'
   server {
       listen 80;
       server_name yourdomain.com;
       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
       }
   }
   EOF
   sudo ln -s /etc/nginx/sites-available/tv-paper-bot /etc/nginx/sites-enabled/
   sudo nginx -t && sudo systemctl reload nginx
   sudo certbot --nginx -d yourdomain.com   # issues + auto-configures HTTPS
   ```

6. **Open the firewall** for web traffic only (keep SSH open too):
   ```bash
   sudo ufw allow 'Nginx Full'
   sudo ufw allow OpenSSH
   ```

7. **Test it's reachable from the outside**, from your own laptop (not the
   server itself):
   ```bash
   curl https://yourdomain.com/health
   ```

Your webhook URL for TradingView is then `https://yourdomain.com/webhook`.

## 2. Test the webhook before wiring TradingView to it

```bash
curl -X POST https://your-app.onrender.com/webhook \
  -H "Content-Type: application/json" \
  -d '{"secret":"YOUR_WEBHOOK_SECRET","symbol":"NIFTY","action":"buy","qty":50,"price":24500,"strategy":"test"}'

curl https://your-app.onrender.com/positions
curl https://your-app.onrender.com/pnl
```

## 3. Set up the TradingView alert

Requires TradingView **Essential plan or higher** — webhooks are blocked on
the free plan.

1. Open your chart → add your Pine Script strategy/indicator.
2. Click **Alert** (clock icon) → create a new alert on your strategy's
   buy/sell condition.
3. Under **Notifications**, enable **Webhook URL** and paste your Render URL
   + `/webhook`, e.g. `https://your-app.onrender.com/webhook`.
4. In the **Message** box, send JSON matching what `main.py` expects:

```json
{
  "secret": "YOUR_WEBHOOK_SECRET",
  "symbol": "{{ticker}}",
  "action": "buy",
  "qty": 50,
  "price": {{close}},
  "strategy": "my-strategy-v1"
}
```

   Use TradingView's built-in placeholders (`{{ticker}}`, `{{close}}`, etc.)
   so the alert fills in live values. Make a second alert (or condition) for
   the sell/exit side with `"action": "sell"`.
5. Save. Fire a manual test alert from TradingView and confirm it shows up
   via `curl https://your-app.onrender.com/trades`.

## 4. What this does NOT do yet

- No live/unrealized P&L (needs a live price feed — `/pnl` tells you where
  to add that).
- No real broker order is ever sent — that's Phase 3, and only after this
  pipeline has run cleanly for a while.
- No shorting logic beyond closing a long position (extend `apply_paper_trade`
  in `main.py` if your strategy shorts).
- Single-secret auth only. Fine for personal paper trading; add proper auth
  before this ever touches real money.
