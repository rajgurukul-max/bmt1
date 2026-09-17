# VPS Deployment Guide — Live Order Placement

Zerodha's Kite Connect API rejects order-placement calls (`place_order`, and
some other endpoints) unless they come from a **static IP you've whitelisted**
in the Kite developer console. This session runs in an ephemeral cloud
container with a rotating egress IP, so it can never satisfy that requirement.
This guide gets you a small, cheap VPS with a fixed IP where the trading
scripts can actually place real orders.

## 1. Pick a VPS

Any provider works — Kite Connect only cares about the IP, not who hosts it.
Pick a region close to India (Mumbai/Bangalore) to minimize latency to NSE.

| Provider | Region w/ static IP | Approx. cost |
|---|---|---|
| DigitalOcean | Bangalore (BLR1) | ~$6/mo (1 vCPU, 1GB) |
| AWS Lightsail | Mumbai (ap-south-1) | ~$5/mo |
| Linode/Akamai | Mumbai | ~$5/mo |
| Hetzner | Singapore/Germany (higher latency) | ~€4/mo |

Any of these is far more than powerful enough — this workload is tiny (a
Python process making REST calls and holding one WebSocket connection).

**Spec to choose**: smallest tier available (1 vCPU, 1GB RAM, ~25GB disk),
Ubuntu 22.04 LTS. A static public IPv4 is assigned automatically on all of
the above — you don't need to request one separately or pay extra for it
(unlike home broadband, where "static IP" is usually a paid ISP add-on).

## 2. Provision and secure the server

```bash
# from your local machine, after creating the VPS and getting its IP
ssh root@<VPS_IP>

# create a non-root user
adduser trader
usermod -aG sudo trader
su - trader

# basic firewall: allow SSH (restrict to your own IP if it's stable) + nothing else inbound
sudo ufw allow OpenSSH
sudo ufw enable

# keep the system patched
sudo apt update && sudo apt upgrade -y

# fail2ban to blunt SSH brute-force attempts
sudo apt install -y fail2ban
```

Set up SSH key auth (not password auth) before you do anything else:
generate a key pair locally (`ssh-keygen`), add the public key to
`~/.ssh/authorized_keys` on the VPS, then in `/etc/ssh/sshd_config` set
`PasswordAuthentication no` and restart `sshd`.

**This box will hold your live trading API keys — treat it like it holds
money, because it does.** Don't install anything else on it, don't reuse it
for other projects, keep it patched.

## 3. Install Python and get the code onto the box

```bash
sudo apt install -y python3.11 python3.11-venv git

git clone <your-fork-or-repo-url> bmt1
cd bmt1/trading

python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

If you don't want to push this repo somewhere the VPS can clone from, `scp`
the `trading/` directory over directly:

```bash
# from your local machine
scp -r trading trader@<VPS_IP>:~/bmt1-trading
```

## 4. Set up credentials

```bash
cp .env.example .env
nano .env   # fill in KITE_API_KEY and KITE_API_SECRET
```

**Never commit `.env`** — it's already gitignored. Copy the values in
directly on the VPS, don't pass them through git or any log.

## 5. Whitelist the VPS's IP in Kite Connect

1. Find the VPS's static IP: `curl https://api.ipify.org` (run this *on the
   VPS*, not your laptop — it must be the IP Zerodha will actually see).
2. Go to https://developers.kite.trade/apps, log in, open your app.
3. Add that IP under **Allowed IPs** (sometimes called redirect/security
   settings, depending on Kite Connect's current UI).
4. Save. This is the one step that fixes the `PermissionException: No IPs
   configured for this app` error we hit today.

## 6. Daily access token refresh

Kite Connect access tokens expire every day — there's no way around this
without automating Zerodha's login + 2FA, which isn't something to script
(it would mean storing your TOTP secret in plaintext on the server, which is
a real security downgrade and likely against Kite's terms). Accept this as
a daily manual step:

```bash
ssh trader@<VPS_IP>
cd bmt1/trading && source venv/bin/activate
python auth.py
# it prints a login URL — open it in YOUR browser, log in, copy the
# request_token from the redirect URL, paste it back into the prompt
```

Do this every trading morning before market open. Consider setting yourself
a personal daily reminder (phone alarm, calendar) for ~9:00 AM IST.

## 7. Run the trading process reliably (systemd)

Don't just `nohup` it in an SSH session — if your SSH connection drops, you
want the process to keep running, and if it crashes, you want it to restart
automatically. Use a systemd service:

```ini
# /etc/systemd/system/angelone-paper-trader.service
[Unit]
Description=ANGELONE paper trader
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=trader
WorkingDirectory=/home/trader/bmt1/trading
ExecStart=/home/trader/bmt1/trading/venv/bin/python paper_trader.py
Restart=on-failure
RestartSec=10
StandardOutput=append:/home/trader/bmt1/trading/logs/paper_trader_stdout.log
StandardError=append:/home/trader/bmt1/trading/logs/paper_trader_stdout.log

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable angelone-paper-trader
sudo systemctl start angelone-paper-trader

# check status / logs
sudo systemctl status angelone-paper-trader
journalctl -u angelone-paper-trader -f
```

Make a second unit file the same way for `live_range_monitor.py` (or
whatever live-order script you're running that day), swapping the
`ExecStart` line. Since access tokens expire daily, you'll `systemctl
restart <service>` each morning after running `auth.py`.

## 8. Verify before trusting it with real orders

Before relying on this for real money, on the VPS:

```bash
python data.py                    # confirm historical data download works
python backtest.py                # confirm the pipeline runs end-to-end
python -c "
from config import load_config; from data import get_kite_client
kite = get_kite_client(load_config())
print(kite.margins())             # confirms auth + API access actually works
print(kite.ltp(['NSE:ANGELONE']))
"
```

Then do a **small, supervised live test** (like today's qty=10 plan) while
watching the Kite app's Orders/GTT/Positions tabs directly, before trusting
it to run unattended.

## 9. Ongoing maintenance checklist

- Daily: run `auth.py`, restart the relevant systemd service(s).
- Weekly: `sudo apt update && sudo apt upgrade`.
- Keep `risk.py`'s daily max-loss and the manual `KILL_SWITCH` file in mind —
  `touch KILL_SWITCH` in the `trading/` directory on the VPS halts new
  entries and flattens open positions immediately, from any SSH session.
- Watch disk usage on `data_cache/` and `logs/` — they're small for one
  symbol but will grow over months; periodically archive or prune old logs.
- If you ever change VPS or the VPS gets a new IP for any reason, you must
  re-whitelist it in the Kite developer console before orders will work
  again.
