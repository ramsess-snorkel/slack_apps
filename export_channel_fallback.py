#!/usr/bin/env python3
"""
Fallback script to export Slack channel metrics when the slash command is unavailable.

This script can be run locally by anyone with a Slack token - no Render/GitHub/cron-job needed.
Use this if /export-channel-metrics fails or Render is down.

Usage:
    python export_channel_fallback.py

Requirements:
    - Python 3.7+
    - Slack token with scopes: conversations:read, users:read, users:read.email, groups:history
    - pip install requests
"""

import os
import sys
from slack_exporter import (
    export_channel_metrics_rows,
    load_dotenv,
    rows_to_csv_bytes,
    clean_token,
    clean_channel_id,
    find_channel_by_name,
    SlackApiError,
)


def main():
    print("=" * 60)
    print("Slack Channel Metrics Exporter (Fallback)")
    print("=" * 60)
    print()

    # Load .env if it exists
    load_dotenv(".env")

    # Get token
    token = os.environ.get("SLACK_BOT_TOKEN") or os.environ.get("SLACK_TOKEN")
    if not token:
        print("ERROR: Missing Slack token.")
        print()
        print("Set it as an environment variable:")
        print("  export SLACK_BOT_TOKEN='xoxb-your-token-here'")
        print()
        print("Or create a .env file with:")
        print("  SLACK_BOT_TOKEN=xoxb-your-token-here")
        print()
        print("To get a token:")
        print("  1. Go to https://api.slack.com/apps")
        print("  2. Create/select your app")
        print("  3. OAuth & Permissions → Install to Workspace")
        print("  4. Copy the 'Bot User OAuth Token' (starts with xoxb-)")
        return 1

    token = clean_token(token)

    # Get channel
    if len(sys.argv) > 1:
        channel_input = sys.argv[1]
    else:
        channel_input = input("Enter channel name or ID (e.g., #ec-terminus-submission or C0123ABCDEF): ").strip()

    if not channel_input:
        print("ERROR: Channel is required.")
        return 1

    # Try to resolve channel - could be ID (C.../G...) or name
    channel_id = clean_channel_id(channel_input)
    
    # If it doesn't look like an ID (doesn't start with C/G/D), try to find by name
    if not (channel_id.startswith("C") or channel_id.startswith("G") or channel_id.startswith("D")):
        print(f"Looking up channel by name: {channel_id}...")
        found_id = find_channel_by_name(token, channel_id)
        if found_id:
            channel_id = found_id
            print(f"Found channel ID: {channel_id}")
        else:
            print()
            print("ERROR: Could not find channel by name.")
            print()
            print("Try one of these:")
            print("  1. Use the channel ID instead:")
            print("     - Right-click channel in Slack → Copy link")
            print("     - Extract the ID from the URL (C... or G... part)")
            print("  2. Use the channel mention format:")
            print("     python export_channel_fallback.py '#ec-terminus-submission'")
            print()
            return 1

    # Output filename
    output_file = os.environ.get("OUTPUT_CSV")
    if not output_file:
        # Generate filename from channel
        safe_name = channel_id.replace("#", "").replace(" ", "_")
        output_file = f"{safe_name}_metrics_fallback.csv"

    print()
    print(f"Exporting metrics for channel: {channel_id}")
    print(f"Output file: {output_file}")
    print()
    print("This may take a while for large channels...")
    print()

    try:
        # Export
        rows = export_channel_metrics_rows(
            token=token,
            channel=channel_id,
            include_bots=False,
            include_deactivated=False,
            scan_history=True,
        )

        # Write CSV
        csv_bytes = rows_to_csv_bytes(rows)
        with open(output_file, "wb") as f:
            f.write(csv_bytes)

        print("=" * 60)
        print(f"✓ Success! Exported {len(rows)} rows to: {output_file}")
        print("=" * 60)
        return 0

    except Exception as e:
        print()
        print("=" * 60)
        print("ERROR: Export failed")
        print("=" * 60)
        print(f"Error: {e}")
        print()
        print("Common issues:")
        print("  - Invalid token: Make sure your token starts with xoxb-")
        print("  - Missing scopes: Need conversations:read, users:read, users:read.email")
        print("  - Private channel: Bot must be invited to the channel")
        print("  - Channel not found: Check the channel name/ID")
        print()
        return 1


if __name__ == "__main__":
    sys.exit(main())

