## Slack channel member emails → CSV

This repo exports the **emails of members in a specific Slack channel** using the Slack Web API.

It also includes an optional **Slack slash command** so teammates can run:
`/export-channel-metrics` and receive a CSV back in Slack.

### Prereqs (Slack)

- Your Slack app/token must have these scopes:
  - `conversations:read`
  - `users:read`
  - `users:read.email` (without this, emails will be blank/missing)
- For message-history stats (message counts + join/leave best-effort), add:
  - `channels:history` (public channels)
  - `groups:history` (private channels)
- If the channel is **private**, the app typically needs to be **added to the channel**.
- If you want the slash command to upload a CSV back to Slack, add:
  - `files:write`
  - `chat:write`

### Get the Channel ID

- In Slack, right-click the channel → **Copy link**
- The link contains `/archives/C0123ABCDEF` — the `C...` part is the Channel ID.

### Run

1) Install deps

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2) Set env vars (recommended; don’t hardcode tokens)

```bash
export SLACK_BOT_TOKEN="xoxb-..."
export SLACK_CHANNEL_ID="C0123ABCDEF"
export OUTPUT_CSV="slack_channel_emails.csv"  # optional
```

Or create a `.env` file in this folder (the script will auto-load it):

```bash
cat > .env <<'EOF'
SLACK_BOT_TOKEN=xoxb-...
SLACK_CHANNEL_ID=C0123ABCDEF
OUTPUT_CSV=slack_channel_emails.csv
EOF
```

3) Export CSV

```bash
python slack_channel_emails.py
```

The CSV will include: `user_id,email,display_name,real_name`

If history scanning is enabled (default), it also includes:
`message_count,joined_at`

### What “steps 6+” mean (API calls)

- **Step 6**: call `conversations.members` repeatedly (pagination) to get all `user_id`s in the channel.
- **Step 7**: call `users.list` repeatedly (pagination) to get all users + emails, then match those `user_id`s.
- **Step 8**: write results to a CSV.

### Message counts + join/leave dates (best-effort)

The script can scan `conversations.history` for the whole channel and compute:
- Per-user message counts (counts only “normal” user messages; excludes bot/system subtypes)
- Best-effort join/leave timestamps by scanning for system event subtypes (not guaranteed to exist)
- `joined_at` (best-effort): unix seconds timestamp derived from the latest join event found in history (often blank if the join event isn’t in retained history).

Options:

```bash
# Full history (default):
python slack_channel_emails.py

# Skip history scan (faster):
python slack_channel_emails.py --no-history-stats

# Scan a specific time window (timestamps are Slack ts, e.g. 1734894493.123456):
python slack_channel_emails.py --oldest 1700000000 --latest 1750000000
```

## Slack slash command: `/export-channel-metrics`

This option lets teammates run an export **from inside Slack**, without installing Python locally.

### How it works

- Slack sends the command payload to your app (we use **Socket Mode** so you don’t need a public HTTPS endpoint for development).
- The app calls the Slack Web API, generates a CSV, then uploads it back to Slack.

### Slack app configuration (one-time)

1) **Enable Socket Mode**
- Slack API → your app → **Socket Mode** → Enable
- Create an app-level token with scope: `connections:write`
- Copy the token (starts with `xapp-...`) → set it as `SLACK_APP_TOKEN`

2) **Create the slash command**
- Slack API → your app → **Slash Commands** → Create New Command
  - Command: `/export-channel-metrics`
  - If Socket Mode is enabled, Slack may not require a Request URL (UI varies).

3) **Event Subscriptions**
- Slack API → your app → **Event Subscriptions**
  - Enable events
  - Under **Subscribe to bot events** add: `app_mention` (Slack often requires at least one; harmless)

4) **OAuth scopes**
Add/reconfirm these scopes and then **Reinstall** the app:
- `conversations:read`
- `users:read`
- `users:read.email`
- `files:write`
- `chat:write`
- `groups:history` (private channel history stats)
- `channels:history` (public channel history stats)

### Run the slash command app (your hosting)

Create/update your `.env`:

```bash
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
```

Run locally:

```bash
python slack_slash_app.py
```

### Troubleshooting: `SSL: CERTIFICATE_VERIFY_FAILED` on macOS

If you see an error like:
`ssl.SSLCertVerificationError: certificate verify failed: unable to get local issuer certificate`

This usually means your Python installation doesn’t have a working CA certificate bundle.

Fix options:

1) **If you installed Python from python.org (common on macOS)**, run the bundled cert installer:
- Find and run: `Install Certificates.command` (it’s installed alongside Python, e.g. under `/Applications/Python 3.x/`)

2) **Use `certifi` as the CA bundle** (works well for venvs):

```bash
source .venv/bin/activate
python -m pip install -U certifi
export SSL_CERT_FILE="$(python -c 'import certifi; print(certifi.where())')"
```

Then retry:

```bash
python slack_slash_app.py
```

### Deploying to the cloud (so it runs independently)

**You don't need to keep your laptop running.** Deploy the app to a cloud service so it's always available.

#### Option 1: Render (recommended — free tier available)

1) **Sign up** at [render.com](https://render.com) (free tier works fine)

2) **Create a new Web Service**:
   - Connect your GitHub repo (or push this code to GitHub first)
   - Render will auto-detect `render.yaml` and use it

3) **Set environment variables** in Render dashboard:
   - `SLACK_BOT_TOKEN` = your `xoxb-...` token
   - `SLACK_APP_TOKEN` = your `xapp-...` token

4) **Deploy** — Render will start the app automatically

The app will stay running 24/7 (free tier allows this). You can stop/restart it from Render's dashboard anytime.

#### Option 2: Fly.io (also has free tier)

```bash
# Install flyctl CLI
curl -L https://fly.io/install.sh | sh

# Login and launch
fly launch
# Follow prompts, set secrets:
fly secrets set SLACK_BOT_TOKEN=xoxb-...
fly secrets set SLACK_APP_TOKEN=xapp-...
```

#### Option 3: Railway / Heroku / AWS EC2

Any platform that runs a persistent Python process works. Set the same environment variables (`SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`) and run `python slack_slash_app.py`.

---

### End-user instructions (what teammates do)

**This command is restricted to workspace admins/owners or channel members, and can only be run in a DM with the bot.**

1) Invite the bot to their channel (private channels require permissions):
- `/invite @snorkel_inspector`

2) Open a **DM** with the app and run:
- `/export-channel-metrics #some-channel`

3) The bot uploads a CSV back into the DM named like:
`<channel_name>_metrics_<unix_timestamp>.csv`

---

## Troubleshooting Guide

### Command fails with `dispatch_failed`

**Most common cause:** Render deployment issue or Socket Mode disconnected.

**Fix steps:**

1. **Check Render deployment status:**
   - Go to Render dashboard → your service → **Events** tab
   - Look for the latest commit - is it "Deploy live" or still "Deploy started"?
   - If still deploying, **wait 1-2 minutes** for it to finish

2. **Check Render logs:**
   - Render dashboard → your service → **Logs** tab
   - Look for:
     - `✓ Health check server listening on port XXXX` (should be there)
     - `⚡️ Bolt app is running!` (confirms Socket Mode connected)
     - Any red error messages

3. **If Socket Mode isn't connecting:**
   - Verify environment variables in Render → **Environment** tab:
     - `SLACK_BOT_TOKEN` = `xoxb-...` (must be set)
     - `SLACK_APP_TOKEN` = `xapp-...` (must be set)
   - If missing, add them and Render will auto-redeploy

4. **Force restart:**
   - Render dashboard → your service → **Manual Deploy** → Deploy latest commit
   - This restarts the app and reconnects Socket Mode

5. **Free tier spin-down:**
   - Render's free tier spins down after inactivity (causes 50+ second delays)
   - First command after spin-down may fail - try again after it wakes up
   - Consider upgrading if this becomes a problem

### Command fails with permission errors

**Error:** "Sorry—this command is restricted to workspace admins/owners or members of the target channel"

**Fix:**
- Make sure you're a **member** of the channel you're trying to export
- For private channels, the bot must also be invited (`/invite @snorkel_inspector`)

### Command fails with `missing_scope`

**Error:** "Export failed. Error: `missing_scope`"

**Fix:**
- Slack API → your app → **OAuth & Permissions**
- Add missing scopes (usually `groups:history` for private channels)
- **Reinstall** the app after adding scopes

### App name shows inconsistently (`email_scraper` vs `snorkel_inspector`)

**Cause:** Slack caches app names in multiple places.

**Fix:**
- Slack API → your app → **Install App** → **Reinstall to Workspace**
- Remove bot from DM and re-add it
- Old file attachments may keep old name (can't change those)

### Local script fails with SSL errors (macOS)

**Error:** `SSL: CERTIFICATE_VERIFY_FAILED`

**Fix:**
```bash
# Option 1: Run Apple's cert installer (if Python from python.org)
# Find: /Applications/Python 3.x/Install Certificates.command

# Option 2: Use certifi
python -m pip install -U certifi
export SSL_CERT_FILE="$(python -c 'import certifi; print(certifi.where())')"
```

### Code changes not taking effect

**Check:**
1. Did you commit and push to GitHub?
2. Is Render showing "Deploy live" for your latest commit?
3. Wait 1-2 minutes after deployment completes before testing

**Quick deploy:**
```bash
git add .
git commit -m "Your change description"
git remote set-url origin https://ghp_YOUR_TOKEN@github.com/ramsess-snorkel/slack_apps.git
git push
git remote set-url origin https://github.com/ramsess-snorkel/slack_apps.git
```

### Keep-alive ping (prevents free tier spin-down)

A GitHub Actions workflow pings the Render service every 10 minutes to keep it awake.

**To enable:**
1. Push the `.github/workflows/keep-alive.yml` file to your repo
2. GitHub Actions will automatically start pinging your Render URL
3. Check it's working: GitHub repo → **Actions** tab → you should see "Keep Render Service Alive" running every 10 minutes

**To update the URL** (if you change your Render service URL):
- Edit `.github/workflows/keep-alive.yml`
- Change `https://slack-apps-11kp.onrender.com` to your new URL
- Commit and push

**Note:** This only works if your repo is public, or if you have GitHub Actions enabled for private repos (free for public repos).




