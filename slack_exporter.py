import csv
import io
import os
import time
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

import requests


SLACK_API_BASE = "https://slack.com/api"


class SlackApiError(RuntimeError):
    pass


def load_dotenv(path: str = ".env") -> None:
    """
    Minimal .env loader (no external deps).
    - Supports lines like KEY=VALUE
    - Ignores blank lines and comments (# ...)
    - Does not overwrite already-set environment variables
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip("'").strip('"')
                if not key:
                    continue
                if os.environ.get(key) is None:
                    os.environ[key] = value
    except FileNotFoundError:
        return


def clean_token(token: str) -> str:
    token = (token or "").strip()
    for prefix in ("OAuth token:", "OAuth Token:", "Token:", "Bearer "):
        if token.startswith(prefix):
            token = token[len(prefix) :].strip()
    return token


def clean_channel_id(channel: str) -> str:
    """
    Accept common inputs and normalize to a raw channel ID:
    - A channel ID: C..., G..., D...
    - A Slack channel URL containing /archives/<ID>
    - A copied link wrapped in <> (Slack formatting)
    - A channel mention like <#C0123ABCDEF|name>
    """
    channel = (channel or "").strip()
    channel = channel.strip("<>").strip()
    channel = channel.lstrip("#").strip()

    # If user passed a mention like #C123|name (after stripping <>)
    if channel.startswith("#") and "|" in channel:
        channel = channel.split("|", 1)[0].lstrip("#").strip()

    if "/archives/" in channel:
        try:
            channel = channel.split("/archives/", 1)[1]
        except Exception:
            pass
        for sep in ("/", "?", "&"):
            if sep in channel:
                channel = channel.split(sep, 1)[0]

    channel = channel.strip().rstrip("+").rstrip()
    if "|" in channel:
        channel = channel.split("|", 1)[0]
    if channel.startswith("#"):
        channel = channel[1:]
    return channel.strip()


def _request_json(
    token: str,
    endpoint: str,
    params: Optional[dict] = None,
    *,
    max_retries: int = 8,
) -> dict:
    url = f"{SLACK_API_BASE}/{endpoint.lstrip('/')}"
    token = clean_token(token)
    headers = {"Authorization": f"Bearer {token}"}

    for attempt in range(max_retries):
        resp = requests.get(url, headers=headers, params=params, timeout=30)

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "1"))
            time.sleep(max(1, retry_after))
            continue

        resp.raise_for_status()
        data = resp.json()

        if data.get("ok") is True:
            return data

        err = data.get("error", "unknown_error")
        if err in {"internal_error", "ratelimited"} and attempt < max_retries - 1:
            time.sleep(1 + attempt)
            continue

        raise SlackApiError(f"{endpoint} failed: {err}")

    raise SlackApiError(f"{endpoint} failed after retries (rate limited)")


def auth_test(token: str) -> dict:
    return _request_json(token, "auth.test")


def conversations_info(token: str, channel_id: str) -> dict:
    return _request_json(token, "conversations.info", params={"channel": channel_id})


def get_channel_member_ids(token: str, channel_id: str) -> List[str]:
    members: List[str] = []
    cursor: Optional[str] = None

    while True:
        params = {"channel": channel_id, "limit": 1000}
        if cursor:
            params["cursor"] = cursor

        data = _request_json(token, "conversations.members", params=params)
        members.extend(data.get("members", []))

        cursor = (data.get("response_metadata") or {}).get("next_cursor") or None
        if not cursor:
            break

    seen = set()
    unique_members = []
    for uid in members:
        if uid not in seen:
            seen.add(uid)
            unique_members.append(uid)
    return unique_members


def build_user_email_map(token: str) -> Dict[str, Tuple[Optional[str], Optional[str], Optional[str], bool, bool]]:
    user_map: Dict[str, Tuple[Optional[str], Optional[str], Optional[str], bool, bool]] = {}
    cursor: Optional[str] = None

    while True:
        params = {"limit": 200}
        if cursor:
            params["cursor"] = cursor

        data = _request_json(token, "users.list", params=params)
        for u in data.get("members", []):
            profile = u.get("profile") or {}
            uid = u.get("id")
            if not uid:
                continue
            email = profile.get("email")
            real_name = u.get("real_name") or profile.get("real_name")
            display_name = profile.get("display_name") or u.get("name")
            deleted = bool(u.get("deleted"))
            is_bot = bool(u.get("is_bot"))
            user_map[uid] = (email, real_name, display_name, deleted, is_bot)

        cursor = (data.get("response_metadata") or {}).get("next_cursor") or None
        if not cursor:
            break

    return user_map


def fetch_user_info(token: str, user_id: str) -> Tuple[Optional[str], Optional[str], Optional[str], bool, bool]:
    data = _request_json(token, "users.info", params={"user": user_id})
    u = data.get("user") or {}
    profile = u.get("profile") or {}
    email = profile.get("email")
    real_name = u.get("real_name") or profile.get("real_name")
    display_name = profile.get("display_name") or u.get("name")
    deleted = bool(u.get("deleted"))
    is_bot = bool(u.get("is_bot"))
    return (email, real_name, display_name, deleted, is_bot)


def iter_conversation_history(
    token: str,
    channel_id: str,
    *,
    oldest: Optional[str] = None,
    latest: Optional[str] = None,
) -> Iterator[dict]:
    cursor: Optional[str] = None
    while True:
        params = {"channel": channel_id, "limit": 200}
        if cursor:
            params["cursor"] = cursor
        if oldest is not None:
            params["oldest"] = oldest
            params["inclusive"] = True
        if latest is not None:
            params["latest"] = latest
            params["inclusive"] = True

        data = _request_json(token, "conversations.history", params=params)
        for m in data.get("messages", []):
            yield m

        cursor = (data.get("response_metadata") or {}).get("next_cursor") or None
        if not cursor:
            break


def _is_countable_user_message(msg: dict) -> bool:
    if msg.get("type") != "message":
        return False
    if not msg.get("user"):
        return False
    return msg.get("subtype") is None


JOIN_SUBTYPES = {"channel_join", "group_join"}


def compute_channel_stats_from_history(
    token: str,
    channel_id: str,
    *,
    oldest: Optional[str] = None,
    latest: Optional[str] = None,
) -> Tuple[Dict[str, int], Dict[str, Optional[str]]]:
    msg_counts: Dict[str, int] = {}
    join_ts: Dict[str, Optional[str]] = {}

    for msg in iter_conversation_history(token, channel_id, oldest=oldest, latest=latest):
        uid = msg.get("user")
        if not uid:
            continue
        ts = msg.get("ts")
        subtype = msg.get("subtype")

        if _is_countable_user_message(msg):
            msg_counts[uid] = msg_counts.get(uid, 0) + 1

        if subtype in JOIN_SUBTYPES and ts:
            prev = join_ts.get(uid)
            if prev is None or float(ts) > float(prev):
                join_ts[uid] = ts

    return msg_counts, join_ts


def slack_ts_to_unix_seconds(ts: Optional[str]) -> str:
    if not ts:
        return ""
    try:
        return str(int(float(ts)))
    except Exception:
        return ""


def get_channel_creator(token: str, channel_id: str) -> Optional[str]:
    """Get the user ID of the channel creator."""
    try:
        info = conversations_info(token, channel_id)
        channel = (info or {}).get("channel") or {}
        return channel.get("creator")
    except Exception:
        return None


def get_user_role(token: str, user_id: str, channel_creator_id: Optional[str]) -> str:
    """
    Determine user's role:
    - "Workspace Admin" if workspace admin/owner
    - "Channel Creator" if they created the channel
    - "Member" otherwise
    """
    try:
        user_info = _request_json(token, "users.info", params={"user": user_id})
        user = (user_info or {}).get("user") or {}
        
        if user.get("is_admin") or user.get("is_owner") or user.get("is_primary_owner"):
            return "Workspace Admin"
    except Exception:
        pass
    
    if channel_creator_id and user_id == channel_creator_id:
        return "Channel Creator"
    
    return "Member"


def export_channel_metrics_rows(
    *,
    token: str,
    channel: str,
    include_bots: bool = False,
    include_deactivated: bool = False,
    oldest: Optional[str] = None,
    latest: Optional[str] = None,
    scan_history: bool = True,
) -> List[dict]:
    token = clean_token(token)
    channel_id = clean_channel_id(channel)

    auth_test(token)
    channel_info_data = conversations_info(token, channel_id)
    channel_creator_id = get_channel_creator(token, channel_id)

    member_ids = get_channel_member_ids(token, channel_id)
    user_map = build_user_email_map(token)

    msg_counts: Dict[str, int] = {}
    join_ts: Dict[str, Optional[str]] = {}

    if scan_history:
        msg_counts, join_ts = compute_channel_stats_from_history(token, channel_id, oldest=oldest, latest=latest)

    discovered_ids = set(member_ids) | set(msg_counts.keys()) | set(join_ts.keys())
    ordered_ids: List[str] = []
    seen_out: set[str] = set()
    for uid in member_ids:
        if uid not in seen_out:
            seen_out.add(uid)
            ordered_ids.append(uid)
    for uid in discovered_ids:
        if uid not in seen_out:
            seen_out.add(uid)
            ordered_ids.append(uid)

    rows: List[dict] = []
    missing_ids: List[str] = []

    for uid in ordered_ids:
        info = user_map.get(uid)
        if not info:
            missing_ids.append(uid)
            continue
        email, real_name, display_name, deleted, is_bot = info

        if deleted and not include_deactivated:
            continue
        if is_bot and not include_bots:
            continue

        role = get_user_role(token, uid, channel_creator_id)

        rows.append(
            {
                "user_id": uid,
                "email": email or "",
                "display_name": display_name or "",
                "real_name": real_name or "",
                "role": role,
                "message_count": str(msg_counts.get(uid, 0)),
                "joined_at": slack_ts_to_unix_seconds(join_ts.get(uid)),
            }
        )

    for uid in missing_ids:
        try:
            email, real_name, display_name, deleted, is_bot = fetch_user_info(token, uid)
        except SlackApiError:
            continue

        if deleted and not include_deactivated:
            continue
        if is_bot and not include_bots:
            continue

        role = get_user_role(token, uid, channel_creator_id)

        rows.append(
            {
                "user_id": uid,
                "email": email or "",
                "display_name": display_name or "",
                "real_name": real_name or "",
                "role": role,
                "message_count": str(msg_counts.get(uid, 0)),
                "joined_at": slack_ts_to_unix_seconds(join_ts.get(uid)),
            }
        )

    return rows


def rows_to_csv_bytes(rows: Iterable[dict]) -> bytes:
    fieldnames = ["user_id", "email", "display_name", "real_name", "role", "message_count", "joined_at"]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in fieldnames})
    return buf.getvalue().encode("utf-8")


