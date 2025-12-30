import os
import json
import time
from pathlib import Path

import feedparser
import requests

STATE_DIR = Path(".state")
STATE_FILE = STATE_DIR / "state.json"

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def clean_text(s: str) -> str:
    if not s:
        return ""
    s = s.replace("\n", " ").replace("\r", " ")
    while "  " in s:
        s = s.replace("  ", " ")
    return s.strip()

def pick_entry_id(entry) -> str:
    return (
        getattr(entry, "id", None)
        or getattr(entry, "guid", None)
        or getattr(entry, "link", None)
        or (getattr(entry, "title", "") + "|" + getattr(entry, "published", ""))
    )

def build_message(entry, source_title: str) -> str:
    title = clean_text(getattr(entry, "title", ""))
    link = getattr(entry, "link", "")
    summary = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
    summary = clean_text(summary)

    if len(summary) > 280:
        summary = summary[:277].rstrip() + "..."

    parts = []
    if title:
        parts.append(f"📰 {title}")
    if summary:
        parts.append(summary)
    if link:
        parts.append(f"Kaynak: {link}")
    if source_title:
        parts.append(f"({source_title})")

    return "\n\n".join(parts).strip()

def telegram_send_message(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": False}
    r = requests.post(url, json=payload, timeout=30)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram error: {data}")

def main():
    feed_url = os.environ.get("FEED_URL", "").strip()
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    tg_channel = os.environ.get("TELEGRAM_CHANNEL", "").strip()
    if not feed_url or not tg_token or not tg_channel:
        raise SystemExit("Missing env vars: FEED_URL, TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL")

    max_items = int(os.environ.get("MAX_ITEMS", "5"))

    state = load_state()
    seen = set(state.get("seen_ids", []))

    feed = feedparser.parse(feed_url)
    source_title = ""
    try:
        source_title = clean_text(feed.feed.get("title", "")) if hasattr(feed, "feed") else ""
    except Exception:
        source_title = ""

    entries = list(getattr(feed, "entries", []) or [])
    if not entries:
        print("No entries found in feed.")
        return

    def entry_sort_key(e):
        pp = getattr(e, "published_parsed", None) or getattr(e, "updated_parsed", None)
        if pp:
            return time.mktime(pp)
        return 0

    entries.sort(key=entry_sort_key, reverse=True)

    to_post = []
    for e in entries:
        eid = pick_entry_id(e)
        if eid in seen:
            continue
        to_post.append((eid, e))
        if len(to_post) >= max_items:
            break

    if not to_post:
        print("No new items to post.")
        return

    to_post.reverse()

    for eid, e in to_post:
        msg = build_message(e, source_title=source_title)
        if not msg:
            continue
        telegram_send_message(tg_token, tg_channel, msg)
        seen.add(eid)
        time.sleep(1)

    seen_list = list(seen)
    if len(seen_list) > 1000:
        seen_list = seen_list[-1000:]

    state["seen_ids"] = seen_list
    save_state(state)
    print(f"Posted {len(to_post)} item(s).")

if __name__ == "__main__":
    main()
