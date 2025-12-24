import os
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional, Tuple

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from slack_exporter import (
    SlackApiError,
    clean_channel_id,
    export_channel_metrics_rows,
    load_dotenv,
    rows_to_csv_bytes,
)


def _parse_channel_arg(text: str) -> Optional[str]:
    """
    Supports:
      - empty (None)
      - channel mention: <#C123|name>
      - channel ID: C123 / G123
      - link containing /archives/<ID>
    """
    t = (text or "").strip()
    return t or None


def _filename(channel_id: str) -> str:
    ts = int(time.time())
    return f"{channel_id}_metrics_{ts}.csv"


def _resolve_target_channel(command_channel_id: str, text: str) -> str:
    arg = _parse_channel_arg(text)
    if not arg:
        return command_channel_id
    return clean_channel_id(arg)


def main() -> None:
    import sys
    sys.stdout.flush()
    sys.stderr.flush()
    
    print("=== Starting Slack Channel Exporter ===", flush=True)
    
    load_dotenv(".env")
    print("Loaded .env file (if exists)", flush=True)

    bot_token = os.environ.get("SLACK_BOT_TOKEN")
    app_token = os.environ.get("SLACK_APP_TOKEN")  # xapp-... for Socket Mode

    print(f"SLACK_BOT_TOKEN present: {bool(bot_token)}", flush=True)
    print(f"SLACK_APP_TOKEN present: {bool(app_token)}", flush=True)

    if not bot_token:
        print("ERROR: Missing SLACK_BOT_TOKEN", flush=True)
        raise SystemExit("Missing SLACK_BOT_TOKEN (xoxb-...).")
    if not app_token:
        print("ERROR: Missing SLACK_APP_TOKEN", flush=True)
        raise SystemExit("Missing SLACK_APP_TOKEN (xapp-...). Enable Socket Mode and set SLACK_APP_TOKEN.")
    
    print("Environment variables validated", flush=True)

    print("Creating Slack Bolt app...", flush=True)
    app = App(token=bot_token)
    print("Slack Bolt app created", flush=True)

    def _is_dm_command(command: dict) -> bool:
        # Slash commands include channel_name; for DMs it is "directmessage".
        channel_name = (command.get("channel_name") or "").lower()
        if channel_name == "directmessage":
            return True
        channel_id = (command.get("channel_id") or "").strip()
        return channel_id.startswith("D")

    def _is_admin_user(client, user_id: str) -> bool:
        info = client.users_info(user=user_id)
        user = (info or {}).get("user") or {}
        return bool(user.get("is_admin") or user.get("is_owner") or user.get("is_primary_owner"))

    def _channel_name_for_filename(client, channel_id: str) -> Optional[str]:
        try:
            info = client.conversations_info(channel=channel_id)
            ch = (info or {}).get("channel") or {}
            name = ch.get("name")
            return name
        except Exception:
            return None

    def _safe_filename_part(s: str) -> str:
        out = []
        for c in (s or ""):
            if c.isalnum() or c in ("-", "_"):
                out.append(c)
            elif c in (" ", "."):
                out.append("_")
        cleaned = "".join(out).strip("_")
        return cleaned or "channel"

    @app.command("/export-channel-metrics")
    def export_channel_metrics(ack, respond, command, client, logger):
        """
        Usage:
          /export-channel-metrics #some-channel
        Notes:
          - For private channels, the bot must be invited to that channel.
          - History scanning requires groups:history (private) / channels:history (public).
        """
        ack()

        # Safety: only allow running this in a DM with the bot.
        if not _is_dm_command(command):
            respond(
                "For safety, this command can only be run in a **DM with me**.\n"
                "Open a DM with the app and run:\n"
                "`/export-channel-metrics #your-channel`"
            )
            return

        # Safety: only workspace admins/owners.
        try:
            if not _is_admin_user(client, command.get("user_id")):
                respond("Sorry—this command is restricted to **workspace admins/owners**.")
                return
        except Exception:
            respond("Could not verify your admin status. Please try again, or contact an admin.")
            return

        try:
            # In DMs, require an explicit target channel argument.
            if not (command.get("text") or "").strip():
                respond("Usage: `/export-channel-metrics #some-channel`")
                return
            channel_id = _resolve_target_channel(command.get("channel_id"), command.get("text", ""))
        except Exception:
            respond("Could not parse channel argument. Try: `/export-channel-metrics` or `/export-channel-metrics #channel`")
            return

        # Let the user know we started (history scans can take a while).
        respond(f"Working on it… exporting metrics for <#{channel_id}>. This may take a bit for large channels.")

        try:
            rows = export_channel_metrics_rows(
                token=bot_token,
                channel=channel_id,
                include_bots=False,
                include_deactivated=False,
                scan_history=True,
            )
            csv_bytes = rows_to_csv_bytes(rows)
        except SlackApiError as e:
            respond(
                "Export failed.\n"
                f"- Error: `{e}`\n"
                "- If this is a private channel, invite the bot to the channel.\n"
                "- If you see `missing_scope`, add the required scopes and reinstall the app."
            )
            return
        except Exception as e:
            logger.exception("Unexpected error during export")
            respond(f"Export failed due to an unexpected error: `{type(e).__name__}`")
            return

        ch_name = _channel_name_for_filename(client, channel_id)
        ts = int(time.time())
        if ch_name:
            filename = f"{_safe_filename_part(ch_name)}_metrics_{ts}.csv"
        else:
            filename = _filename(channel_id)

        # Upload as a file to the DM where the command was run (never to the target channel).
        try:
            client.files_upload_v2(
                channel=command.get("channel_id"),
                filename=filename,
                title=filename,
                file=csv_bytes,
                initial_comment=f"Here are the metrics for <#{channel_id}>",
            )
        except Exception as e:
            logger.exception("Failed to upload file")
            respond(
                "Export succeeded, but uploading the CSV failed.\n"
                "- Ensure the app has `files:write` scope and is allowed to post in this channel."
            )
            return

        respond(f"Done. Uploaded `{filename}`.")

    # Start a minimal HTTP server for Render's health checks (Web Service requires a port)
    class HealthCheckHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
        
        def log_message(self, format, *args):
            pass  # Suppress HTTP server logs

    port = int(os.environ.get("PORT", "10000"))
    print(f"Starting health check server on port {port}...", flush=True)
    http_server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    http_thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    http_thread.start()
    print(f"✓ Health check server listening on port {port}", flush=True)

    # Start Socket Mode (this blocks)
    print("Starting Socket Mode connection to Slack...", flush=True)
    try:
        handler = SocketModeHandler(app, app_token)
        print("SocketModeHandler created, starting connection...", flush=True)
        handler.start()
        print("⚡️ Bolt app is running!", flush=True)
    except Exception as e:
        print(f"ERROR: Failed to start Socket Mode: {e}", flush=True)
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()


