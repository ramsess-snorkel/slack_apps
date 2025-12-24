def main() -> int:
    import argparse

    from slack_exporter import export_channel_metrics_rows, load_dotenv, rows_to_csv_bytes

    load_dotenv(".env")

    parser = argparse.ArgumentParser(description="Export Slack channel member emails/metrics to CSV.")
    parser.add_argument("--channel", default=os.environ.get("SLACK_CHANNEL_ID"), help="Channel ID or link")
    parser.add_argument("--token", default=os.environ.get("SLACK_BOT_TOKEN"), help="Slack token (xoxb-...)")
    parser.add_argument("--out", default=os.environ.get("OUTPUT_CSV", "slack_channel_emails.csv"), help="Output CSV path")
    parser.add_argument("--include-bots", action="store_true", help="Include bot users")
    parser.add_argument("--include-deactivated", action="store_true", help="Include deactivated users")
    parser.add_argument("--oldest", default=os.environ.get("OLDEST_TS"), help="Oldest timestamp (Slack ts) for history scan (optional)")
    parser.add_argument("--latest", default=os.environ.get("LATEST_TS"), help="Latest timestamp (Slack ts) for history scan (optional)")
    parser.add_argument("--no-history-stats", action="store_true", help="Skip scanning conversations.history")
    args = parser.parse_args()

    if not args.token:
        raise SystemExit("Missing token. Set SLACK_BOT_TOKEN or pass --token.")
    if not args.channel:
        raise SystemExit("Missing channel. Set SLACK_CHANNEL_ID or pass --channel.")

    rows = export_channel_metrics_rows(
        token=args.token,
        channel=args.channel,
        include_bots=bool(args.include_bots),
        include_deactivated=bool(args.include_deactivated),
        oldest=args.oldest if args.oldest else None,
        latest=args.latest if args.latest else None,
        scan_history=not bool(args.no_history_stats),
    )

    csv_bytes = rows_to_csv_bytes(rows)
    with open(args.out, "wb") as f:
        f.write(csv_bytes)

    print(f"Wrote {len(rows)} rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


