from flask import Flask, render_template_string
import sqlite3
import shutil
from pathlib import Path
from datetime import datetime, timedelta, date
from collections import Counter
import re

# Paths to Messages DB
MESSAGES_DB = Path.home() / "Library" / "Messages" / "chat.db"
TEMP_DB = Path.cwd() / "chat_copy.db"

# Contacts DB dir (Apple address book)
CONTACTS_SOURCES_DIR = (
    Path.home()
    / "Library"
    / "Application Support"
    / "AddressBook"
    / "Sources"
)

app = Flask(__name__)

# Rough emoji matcher (not perfect, but good enough for a fun "Wrapped")
EMOJI_RE = re.compile(
    r"[\U0001F300-\U0001FAFF\U00002700-\U000027BF\U00002600-\U000026FF]"
)


def copy_database(src: Path, dst: Path) -> None:
    """Copy the Messages DB so we safely read from a snapshot."""
    if not src.exists():
        raise FileNotFoundError(f"Messages database not found at: {src}")
    shutil.copy2(src, dst)


def apple_date_to_datetime(value):
    """
    Convert Apple's Messages date format to a Python datetime.

    Messages uses time since 2001-01-01 in various units (ns, s, µs).
    This uses some heuristics to handle common cases.
    """
    if value is None:
        return None
    try:
        v = int(value)
    except (TypeError, ValueError):
        return None

    apple_epoch = datetime(2001, 1, 1)

    # Heuristics: guess units
    if v > 10**12:  # likely nanoseconds
        seconds = v / 1_000_000_000
    elif v > 10**9:  # likely seconds
        seconds = v
    else:  # microseconds-ish
        seconds = v / 1_000_000

    return apple_epoch + timedelta(seconds=seconds)


def normalize_phone(raw: str) -> str:
    if not raw:
        return ""
    digits = "".join(ch for ch in raw if ch.isdigit())
    # Drop leading "1" for US-style numbers like +1XXXXXXXXXX
    if len(digits) > 10 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def normalize_email(raw: str) -> str:
    if not raw:
        return ""
    return raw.strip().lower()


def normalize_address(raw: str) -> str:
    """Normalize a handle.id-style address (phone or email)."""
    if not raw:
        return ""
    if "@" in raw:
        return normalize_email(raw)
    return normalize_phone(raw)


def load_contact_names():
    """
    Try to read contact names from the local Contacts database.

    Returns:
      { normalized_address (phone/email) : "Full Name" }
    """
    contact_names = {}

    if not CONTACTS_SOURCES_DIR.exists():
        return contact_names

    for src in CONTACTS_SOURCES_DIR.iterdir():
        if not src.is_dir():
            continue
        for db_path in src.glob("*.abcddb"):
            try:
                conn = sqlite3.connect(str(db_path))
                cur = conn.cursor()

                # Phones
                try:
                    cur.execute(
                        """
                        SELECT
                            pn.ZFULLNUMBER,
                            r.ZFIRSTNAME,
                            r.ZLASTNAME,
                            r.ZORGANIZATION
                        FROM ZABCDPHONENUMBER pn
                        JOIN ZABCDRECORD r ON pn.ZOWNER = r.Z_PK
                        """
                    )
                    for number, first, last, org in cur.fetchall():
                        if not number:
                            continue
                        norm = normalize_phone(number)
                        if not norm:
                            continue
                        name_parts = [part for part in [first, last] if part]
                        name = " ".join(name_parts).strip()
                        if not name:
                            name = (org or "").strip()
                        if not name:
                            continue
                        contact_names.setdefault(norm, name)
                except Exception:
                    # Schema may differ; skip quietly
                    pass

                # Emails
                try:
                    cur.execute(
                        """
                        SELECT
                            em.ZADDRESS,
                            r.ZFIRSTNAME,
                            r.ZLASTNAME,
                            r.ZORGANIZATION
                        FROM ZABCDEMAILADDRESS em
                        JOIN ZABCDRECORD r ON em.ZOWNER = r.Z_PK
                        """
                    )
                    for addr, first, last, org in cur.fetchall():
                        if not addr:
                            continue
                        norm = normalize_email(addr)
                        if not norm:
                            continue
                        name_parts = [part for part in [first, last] if part]
                        name = " ".join(name_parts).strip()
                        if not name:
                            name = (org or "").strip()
                        if not name:
                            continue
                        contact_names.setdefault(norm, name)
                except Exception:
                    pass

                conn.close()
            except Exception:
                # If any contact DB fails, just continue
                continue

    return contact_names


def load_handles_and_chats(conn, contact_names):
    """
    Load:
      - handle_names: {handle_rowid: display_name (prefers Contacts)}
      - chat_info: {chat_rowid: {"name": str, "is_group": bool}}

    For 1-on-1 chats, we use the contact name if available.
    For group chats, we build friendly names like "Alex, Sam + 3 others".
    """
    cur = conn.cursor()

    # 1) Handles -> names
    handle_names = {}
    cur.execute("SELECT ROWID, id FROM handle")
    for rowid, handle_id in cur.fetchall():
        addr = handle_id or ""
        norm_addr = normalize_address(addr)
        name_from_contacts = contact_names.get(norm_addr)
        if name_from_contacts:
            display_name = name_from_contacts
        else:
            display_name = addr if addr else "Unknown"
        handle_names[rowid] = display_name

    # 2) Chats -> names + is_group
    chat_info = {}
    cur.execute(
        """
        SELECT
            chat.ROWID,
            chat.display_name,
            chat.chat_identifier,
            COUNT(chj.handle_id) as participant_count
        FROM chat
        LEFT JOIN chat_handle_join chj ON chj.chat_id = chat.ROWID
        GROUP BY chat.ROWID
        """
    )
    rows = cur.fetchall()

    # We'll need another cursor to look up participant handles
    cur2 = conn.cursor()

    for rowid, display_name, chat_identifier, participant_count in rows:
        is_group = participant_count and participant_count > 1

        if is_group:
            # Group chat
            if display_name and display_name.strip():
                # User-named group chat (what you see in Messages)
                name = display_name
            else:
                # No custom name – build one from participants
                cur2.execute(
                    "SELECT handle_id FROM chat_handle_join WHERE chat_id = ?",
                    (rowid,),
                )
                handle_ids = [h_id for (h_id,) in cur2.fetchall() if h_id is not None]
                participant_names = [
                    handle_names.get(h_id, "Unknown") for h_id in handle_ids
                ]

                # Deduplicate while preserving order
                seen = set()
                unique_names = []
                for n in participant_names:
                    if n not in seen:
                        seen.add(n)
                        unique_names.append(n)

                if not unique_names:
                    name = f"Group chat #{rowid}"
                elif len(unique_names) == 1:
                    name = unique_names[0]
                elif len(unique_names) == 2:
                    name = f"{unique_names[0]}, {unique_names[1]}"
                else:
                    others = len(unique_names) - 2
                    name = f"{unique_names[0]}, {unique_names[1]} + {others} others"
        else:
            # 1-on-1 chat — try to use the contact name from the single handle
            cur2.execute(
                "SELECT handle_id FROM chat_handle_join WHERE chat_id = ? LIMIT 1",
                (rowid,),
            )
            res = cur2.fetchone()
            if res:
                h_id = res[0]
                name = handle_names.get(h_id)
            else:
                name = display_name or chat_identifier or f"Chat #{rowid}"

        chat_info[rowid] = {"name": name, "is_group": is_group}

    return handle_names, chat_info


def load_messages(conn, handle_names, chat_info):
    """
    Load messages from DB.

    We map each message to a "conversation key":
      - If it belongs to a chat with a name, we use the chat name (group or named thread).
      - Otherwise we fall back to the handle (contact).

    Returns:
      list of {is_from_me, datetime, conv_key, conv_name, text}
      (ALL messages in the DB)
    """
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            m.ROWID,
            m.is_from_me,
            m.date,
            m.handle_id,
            m.text,
            m.attributedBody,
            cmj.chat_id
        FROM message m
        LEFT JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
        WHERE m.handle_id IS NOT NULL OR cmj.chat_id IS NOT NULL
        """
    )

    messages = []
    for msg_id, is_from_me, date_val, handle_id, text, attributed_body, chat_id in cur.fetchall():
        dt = apple_date_to_datetime(date_val)
        if dt is None:
            continue

        if chat_id and chat_id in chat_info:
            conv_name = chat_info[chat_id]["name"]
            conv_key = f"chat:{chat_id}"
        elif handle_id is not None:
            conv_name = handle_names.get(handle_id, "Unknown")
            conv_key = f"handle:{handle_id}"
        else:
            conv_name = "Unknown"
            conv_key = f"unknown:{msg_id}"

        # Try to extract text from either text field or attributedBody
        message_text = text or ""
        if not message_text and attributed_body:
            # attributedBody is a binary blob, try to decode it
            try:
                # Simple heuristic: look for readable text in the blob
                if isinstance(attributed_body, bytes):
                    decoded = attributed_body.decode('utf-8', errors='ignore')
                    # Extract text between common markers or just use printable chars
                    message_text = ''.join(c for c in decoded if c.isprintable() or c.isspace()).strip()
            except:
                pass

        messages.append(
            {
                "is_from_me": bool(is_from_me),
                "datetime": dt,
                "conv_key": conv_key,
                "conv_name": conv_name,
                "text": message_text,
            }
        )

    return messages


def compute_stats(messages, top_n=15, top_emoji_n=20):
    """
    Compute stats for a given list of messages.

    Average length counts ONLY actual text messages:
      - text is non-empty after stripping whitespace.
    Average response time is calculated as the time between receiving a message
    and sending the next message in hours.
    Tracks both your response time (when you reply to them) and their response time (when they reply to you).
    """
    if not messages:
        return {
            "total_messages": 0,
            "sent_count": 0,
            "received_count": 0,
            "start_date": None,
            "end_date": None,
            "top_contacts": [],
            "top_contact": None,
            "busiest_day": None,
            "longest_contact_streak": None,
            "top_emoji": [],
        }

    # Sort messages by datetime for response time calculation
    messages = sorted(messages, key=lambda m: m["datetime"])
    
    per_conv = {}
    day_counts = Counter()
    emoji_counter = Counter()
    word_counter = Counter()

    total_messages = len(messages)
    sent_count = 0
    received_count = 0
    all_dates = []

    for msg in messages:
        conv_key = msg["conv_key"]
        name = msg["conv_name"]
        dt = msg["datetime"]
        day = dt.date()
        all_dates.append(day)
        day_counts[day] += 1

        if conv_key not in per_conv:
            per_conv[conv_key] = {
                "name": name,
                "sent": 0,
                "received": 0,
                "total": 0,
                "messages": 0,      # all messages (text + non-text)
                "days_active": set(),
                "text_words": 0,
                "text_messages": 0, # only non-empty text messages
                "last_received_time": None,  # track last received message time
                "last_sent_time": None,  # track last sent message time
                "your_response_times": [],  # your response times in hours
                "their_response_times": [],  # their response times in hours
            }

        entry = per_conv[conv_key]

        if msg["is_from_me"]:
            entry["sent"] += 1
            sent_count += 1
            # Calculate YOUR response time if we have a previous received message
            if entry["last_received_time"] is not None:
                time_diff = (dt - entry["last_received_time"]).total_seconds() / 3600  # hours
                # Only count responses within 24 hours as meaningful
                if time_diff <= 48:
                    entry["your_response_times"].append(time_diff)
                entry["last_received_time"] = None  # reset after responding
            # Update last sent time for tracking their responses
            entry["last_sent_time"] = dt
        else:
            entry["received"] += 1
            received_count += 1
            # Calculate THEIR response time if we have a previous sent message
            if entry["last_sent_time"] is not None:
                time_diff = (dt - entry["last_sent_time"]).total_seconds() / 3600  # hours
                # Only count responses within 24 hours as meaningful
                if time_diff <= 48:
                    entry["their_response_times"].append(time_diff)
                entry["last_sent_time"] = None  # reset after they respond
            # Update last received time for tracking your responses
            entry["last_received_time"] = dt

        entry["total"] += 1
        entry["messages"] += 1
        entry["days_active"].add(day)

        text_content = (msg["text"] or "").strip()
        if text_content:
            # Remove emojis for word counting
            text_no_emoji = EMOJI_RE.sub('', text_content)
            words = text_no_emoji.split()
            word_count = len(words)
            entry["text_words"] += word_count
            entry["text_messages"] += 1
            
            # Count emojis
            for e in EMOJI_RE.findall(text_content):
                emoji_counter[e] += 1
            
            # Count words (lowercase, filter out short words, common words, and technical metadata)
            common_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'should', 'could', 'may', 'might', 'must', 'can', 'i', 'you', 'he', 'she', 'it', 'we', 'they', 'my', 'your', 'his', 'her', 'its', 'our', 'their', 'me', 'him', 'them', 'this', 'that', 'these', 'those', 'am', 'im', 'id', 'ill', 'ive', 'dont', 'doesnt', 'didnt', 'wont', 'wouldnt', 'shouldnt', 'couldnt', 'cant', 'isnt', 'arent', 'wasnt', 'werent', 'hasnt', 'havent', 'hadnt'}
            for word in words:
                clean_word = word.lower().strip('.,!?;:"\'()[]{}').strip()
                # Filter out technical metadata (contains __ or ns or very long words)
                if (len(clean_word) > 2 and 
                    len(clean_word) < 20 and  # Skip very long technical strings
                    clean_word not in common_words and
                    '__' not in clean_word and  # Skip __kimmessage type strings
                    not clean_word.startswith('ns') and  # Skip nsvalue, nsnumber, etc.
                    clean_word.isalpha()):  # Only alphabetic characters (no numbers or special chars)
                    word_counter[clean_word] += 1

    # Per-conversation stats & longest streak with someone
    longest_contact_streak = None
    best_contact_streak_len = 0

    for entry in per_conv.values():
        entry["days_active_count"] = len(entry["days_active"])
        if entry["text_messages"] > 0:
            entry["avg_length"] = entry["text_words"] / entry["text_messages"]
        else:
            entry["avg_length"] = 0
        
        # Calculate average response times
        if entry["your_response_times"]:
            entry["your_avg_response_hours"] = sum(entry["your_response_times"]) / len(entry["your_response_times"])
        else:
            entry["your_avg_response_hours"] = None
        
        if entry["their_response_times"]:
            entry["their_avg_response_hours"] = sum(entry["their_response_times"]) / len(entry["their_response_times"])
        else:
            entry["their_avg_response_hours"] = None
        
        # Debug: print conversations with 0 avg length but many messages
        if entry["avg_length"] == 0 and entry["total"] > 10:
            print(f"DEBUG: {entry['name']} - Total: {entry['total']}, Text msgs: {entry['text_messages']}, Words: {entry['text_words']}")

        # Per-conversation longest streak (any messages, not just text)
        if entry["days_active"]:
            days_sorted = sorted(entry["days_active"])
            current_len = 1
            max_len = 1
            best_start = days_sorted[0]
            best_end = days_sorted[0]

            for i in range(1, len(days_sorted)):
                if days_sorted[i] == days_sorted[i - 1] + timedelta(days=1):
                    current_len += 1
                else:
                    if current_len > max_len:
                        max_len = current_len
                        best_start = days_sorted[i - current_len]
                        best_end = days_sorted[i - 1]
                    current_len = 1

            if current_len > max_len:
                max_len = current_len
                best_start = days_sorted[-current_len]
                best_end = days_sorted[-1]

            entry["streak_length"] = max_len
            entry["streak_start"] = best_start
            entry["streak_end"] = best_end

            if max_len > best_contact_streak_len:
                best_contact_streak_len = max_len
                longest_contact_streak = {
                    "name": entry["name"],
                    "length": max_len,
                    "start": best_start,
                    "end": best_end,
                }
        else:
            entry["streak_length"] = 0
            entry["streak_start"] = None
            entry["streak_end"] = None

    # All conversations with 100+ messages (will be filtered/sorted client-side to show top 15)
    top_contacts = sorted(
        [e for e in per_conv.values() if e["total"] >= 100],
        key=lambda e: e["total"], 
        reverse=True
    )
    top_contact = top_contacts[0] if top_contacts else None

    # Busiest day overall
    busiest_day = None
    if day_counts:
        d, c = max(day_counts.items(), key=lambda x: x[1])
        busiest_day = {"date": d, "count": c}

    start_date = min(all_dates)
    end_date = max(all_dates)

    # Top emoji (from text messages only)
    top_emoji = [
        {"emoji": emoji, "count": count}
        for emoji, count in emoji_counter.most_common(top_emoji_n)
    ]
    
    # Top words (from text messages only)
    top_words = [
        {"word": word, "count": count}
        for word, count in word_counter.most_common(top_emoji_n)
    ]

    return {
        "total_messages": total_messages,
        "sent_count": sent_count,
        "received_count": received_count,
        "start_date": start_date,
        "end_date": end_date,
        "top_contacts": top_contacts,
        "top_contact": top_contact,
        "busiest_day": busiest_day,
        "longest_contact_streak": longest_contact_streak,
        "top_emoji": top_emoji,
        "top_words": top_words,
    }


TEMPLATE = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Messages Wrapped</title>
  <style>
    body {
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif;
      margin: 0;
      padding: 0;
      background: radial-gradient(circle at top left, #3b82f6, #0f172a);
      color: #f9fafb;
    }
    .container {
      max-width: 960px;
      margin: 0 auto;
      padding: 32px 16px 48px;
    }
    .card {
      background: rgba(15, 23, 42, 0.92);
      border-radius: 24px;
      padding: 24px 24px 28px;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.4);
      backdrop-filter: blur(20px);
      border: 1px solid rgba(148, 163, 184, 0.35);
    }
    h1 {
      font-size: 40px;
      margin-bottom: 8px;
    }
    h2 {
      font-size: 24px;
      margin-top: 12px;
      margin-bottom: 4px;
    }
    h3 {
      font-size: 18px;
      margin-top: 14px;
      margin-bottom: 6px;
    }
    .subtitle {
      color: #cbd5f5;
      margin-bottom: 16px;
    }
    .period-select-row {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 12px;
    }
    .period-label {
      font-size: 14px;
      color: #e5e7eb;
    }
    select {
      background: rgba(15, 23, 42, 0.95);
      color: #e5e7eb;
      border-radius: 999px;
      border: 1px solid rgba(148, 163, 184, 0.7);
      padding: 6px 12px;
      font-size: 14px;
      outline: none;
    }
    select:focus {
      border-color: #60a5fa;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 16px;
      margin-bottom: 16px;
    }
    .stat {
      background: radial-gradient(circle at top left, #22c55e33, #111827dd);
      border-radius: 18px;
      padding: 12px 14px;
      border: 1px solid rgba(55, 65, 81, 0.8);
    }
    .stat-label {
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: #9ca3af;
      margin-bottom: 4px;
    }
    .stat-value {
      font-size: 22px;
      font-weight: 600;
    }
    .feature-row {
      margin: 10px 0 18px;
    }
    .feature-card {
      background: linear-gradient(135deg, #a855f7cc, #ec4899cc);
      border-radius: 22px;
      padding: 16px 18px;
      box-shadow: 0 18px 35px rgba(0, 0, 0, 0.45);
    }
    .feature-title {
      font-size: 14px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      opacity: 0.9;
      margin-bottom: 6px;
    }
    .feature-main {
      font-size: 22px;
      font-weight: 600;
      margin-bottom: 4px;
    }
    .feature-sub {
      font-size: 13px;
      opacity: 0.9;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 10px;
      font-size: 14px;
    }
    th, td {
      padding: 8px 10px;
      text-align: left;
    }
    th {
      border-bottom: 1px solid rgba(148, 163, 184, 0.6);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: #9ca3af;
    }
    th.sortable {
      cursor: pointer;
      user-select: none;
      position: relative;
    }
    th.sortable:hover {
      color: #60a5fa;
    }
    th.sortable .sort-arrow {
      font-size: 14px;
      margin-left: 4px;
      opacity: 0.5;
    }
    th.sortable.asc .sort-arrow::before {
      content: '↑';
      opacity: 1;
    }
    th.sortable.desc .sort-arrow::before {
      content: '↓';
      opacity: 1;
    }
    th.sortable.asc .sort-arrow,
    th.sortable.desc .sort-arrow {
      opacity: 1;
      color: #60a5fa;
    }
    tbody tr:nth-child(even) {
      background: rgba(15, 23, 42, 0.9);
    }
    tbody tr:nth-child(odd) {
      background: rgba(15, 23, 42, 0.7);
    }
    tbody tr:hover {
      background: rgba(55, 65, 81, 0.95);
    }
    .name-col {
      font-weight: 500;
    }
    .small {
      font-size: 12px;
      color: #9ca3af;
    }
    .emoji-list {
      display: flex;
      flex-wrap: wrap;
      gap: 8px 16px;
      margin-top: 6px;
    }
    .emoji-item {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 18px;
      background: rgba(15, 23, 42, 0.9);
      padding: 6px 10px;
      border-radius: 999px;
      border: 1px solid rgba(55, 65, 81, 0.8);
    }
    .emoji-count {
      font-size: 12px;
      color: #9ca3af;
    }
    .period-section {
      display: none;
      margin-top: 10px;
    }
    .period-section.active {
      display: block;
    }
    @media (max-width: 600px) {
      h1 { font-size: 30px; }
      .card { padding: 18px 16px 20px; }
      .feature-main { font-size: 20px; }
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="card">
      <h1>Your Messages Wrapped</h1>
      <div class="subtitle">
        View your iMessage history by year or across all time.
      </div>

      <div class="period-select-row">
        <span class="period-label">View period:</span>
        <select id="period-select">
          {% for key, label in period_labels %}
            <option value="{{ key }}" {% if key == default_period %}selected{% endif %}>
              {{ label }}
            </option>
          {% endfor %}
        </select>
      </div>

      {% macro period_block(key, label, stats) %}
      <div class="period-section {% if key == default_period %}active{% endif %}" id="period-{{ key }}">
        <h2>{{ label }}</h2>
        {% if stats.total_messages == 0 %}
          <p class="small">No messages in this period.</p>
        {% else %}
          <p class="small">
            From {{ stats.start_date.strftime("%b %d, %Y") }}
            to {{ stats.end_date.strftime("%b %d, %Y") }}.
          </p>

          <div class="grid">
            <div class="stat">
              <div class="stat-label">Total Messages</div>
              <div class="stat-value">{{ stats.total_messages }}</div>
            </div>
            <div class="stat">
              <div class="stat-label">Sent</div>
              <div class="stat-value">{{ stats.sent_count }}</div>
            </div>
            <div class="stat">
              <div class="stat-label">Received</div>
              <div class="stat-value">{{ stats.received_count }}</div>
            </div>
            {% if stats.busiest_day %}
            <div class="stat">
              <div class="stat-label">Busiest Day</div>
              <div class="stat-value">
                {{ stats.busiest_day.date.strftime("%b %d, %Y") }}
                <span class="small">({{ stats.busiest_day.count }} msgs)</span>
              </div>
            </div>
            {% endif %}
          </div>

          {% if stats.longest_contact_streak %}
          <div class="feature-row">
            <div class="feature-card">
              <div class="feature-title">Longest Daily Streak With Someone</div>
              <div class="feature-main">
                {{ stats.longest_contact_streak.name }} — {{ stats.longest_contact_streak.length }} days
              </div>
              <div class="feature-sub">
                From {{ stats.longest_contact_streak.start.strftime("%b %d, %Y") }}
                to {{ stats.longest_contact_streak.end.strftime("%b %d, %Y") }}.
              </div>
            </div>
          </div>
          {% endif %}

          {% if stats.top_emoji %}
          <h3>Top Emoji</h3>
          <p class="small">Most-used emoji in this period (from text messages).</p>
          <div class="emoji-list">
            {% for item in stats.top_emoji %}
            <div class="emoji-item">
              <span>{{ item.emoji }}</span>
              <span class="emoji-count">× {{ item.count }}</span>
            </div>
            {% endfor %}
          </div>
          {% endif %}

          {% if stats.top_words %}
          <h3>Top Words</h3>
          <p class="small">Most frequently used words in this period (common words filtered out).</p>
          <div class="emoji-list">
            {% for item in stats.top_words %}
            <div class="emoji-item">
              <span style="font-size: 18px;">{{ item.word }}</span>
              <span class="emoji-count">× {{ item.count }}</span>
            </div>
            {% endfor %}
          </div>
          {% endif %}

          <h3>Top Conversations</h3>
          <p class="small">
            Top {{ stats.top_contacts|length }} chats by total messages.
            (Group chats are listed by group name.)
            Average length counts only text messages.
          </p>
          <table class="sortable-table" data-period="{{ key }}">
            <thead>
              <tr>
                <th>#</th>
                <th class="sortable" data-sort="name">Chat <span class="sort-arrow">⇅</span></th>
                <th class="sortable" data-sort="sent">Sent <span class="sort-arrow">⇅</span></th>
                <th class="sortable" data-sort="received">Received <span class="sort-arrow">⇅</span></th>
                <th class="sortable" data-sort="total">Total <span class="sort-arrow">⇅</span></th>
                <th class="sortable" data-sort="avg_length">Avg Words <span class="sort-arrow">⇅</span></th>
                <th class="sortable" data-sort="your_response">Your Avg Response Time <span class="sort-arrow">⇅</span></th>
                <th class="sortable" data-sort="their_response">Their Avg Response Time <span class="sort-arrow">⇅</span></th>
                <th class="sortable" data-sort="active_days">Active Days <span class="sort-arrow">⇅</span></th>
              </tr>
            </thead>
            <tbody>
              {% for contact in stats.top_contacts %}
              <tr{% if loop.index > 15 %} style="display: none;"{% endif %}>
                <td>{{ loop.index }}</td>
                <td class="name-col" data-value="{{ contact.name }}">{{ contact.name }}</td>
                <td data-value="{{ contact.sent }}">{{ contact.sent }}</td>
                <td data-value="{{ contact.received }}">{{ contact.received }}</td>
                <td data-value="{{ contact.total }}">{{ contact.total }}</td>
                <td data-value="{{ contact.avg_length }}">{{ '-' if contact.avg_length == 0 else '%.1f'|format(contact.avg_length) }}</td>
                <td data-value="{{ contact.your_avg_response_hours if contact.your_avg_response_hours is not none else 999999 }}">{% if contact.your_avg_response_hours is not none %}{{ '%.1f'|format(contact.your_avg_response_hours) }}h{% else %}-{% endif %}</td>
                <td data-value="{{ contact.their_avg_response_hours if contact.their_avg_response_hours is not none else 999999 }}">{% if contact.their_avg_response_hours is not none %}{{ '%.1f'|format(contact.their_avg_response_hours) }}h{% else %}-{% endif %}</td>
                <td data-value="{{ contact.days_active_count }}">{{ contact.days_active_count }}</td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
        {% endif %}
      </div>
      {% endmacro %}

      {{ period_block("all", "All Time", stats_total) }}

      {% for year, stats in stats_by_year %}
        {{ period_block(year, year ~ " Wrapped", stats) }}
      {% endfor %}
    </div>
  </div>

  <script>
    (function() {
      const select = document.getElementById('period-select');
      const sections = document.querySelectorAll('.period-section');

      function updatePeriod() {
        const value = select.value;
        sections.forEach(sec => {
          if (sec.id === 'period-' + value) {
            sec.classList.add('active');
          } else {
            sec.classList.remove('active');
          }
        });
      }

      select.addEventListener('change', updatePeriod);
      updatePeriod();

      // Table sorting functionality
      document.querySelectorAll('.sortable-table').forEach(table => {
        const headers = table.querySelectorAll('th.sortable');
        let currentSort = { column: null, direction: 'asc' };

        headers.forEach(header => {
          header.addEventListener('click', function() {
            const sortKey = this.dataset.sort;
            const tbody = table.querySelector('tbody');
            const rows = Array.from(tbody.querySelectorAll('tr'));

            // Toggle direction if clicking same column
            if (currentSort.column === sortKey) {
              currentSort.direction = currentSort.direction === 'asc' ? 'desc' : 'asc';
            } else {
              currentSort.column = sortKey;
              currentSort.direction = 'asc';
            }

            // Remove all sort classes
            headers.forEach(h => h.classList.remove('asc', 'desc'));
            // Add current sort class
            this.classList.add(currentSort.direction);

            // Get column index
            const columnIndex = Array.from(this.parentElement.children).indexOf(this);

            // Sort rows
            rows.sort((a, b) => {
              const aCell = a.children[columnIndex];
              const bCell = b.children[columnIndex];
              
              let aVal = aCell.dataset.value;
              let bVal = bCell.dataset.value;

              // Try to parse as number
              const aNum = parseFloat(aVal);
              const bNum = parseFloat(bVal);

              let comparison;
              if (!isNaN(aNum) && !isNaN(bNum)) {
                comparison = aNum - bNum;
              } else {
                // String comparison
                comparison = aVal.localeCompare(bVal);
              }

              return currentSort.direction === 'asc' ? comparison : -comparison;
            });

            // Re-append rows in new order, showing only top 15
            rows.forEach((row, index) => {
              if (index < 15) {
                row.style.display = '';
                tbody.appendChild(row);
                // Update row number
                row.children[0].textContent = index + 1;
              } else {
                row.style.display = 'none';
                tbody.appendChild(row);
              }
            });
          });
        });
      });
    })();
  </script>
</body>
</html>
"""


@app.route("/")
def index():
    if not MESSAGES_DB.exists():
        return (
            f"<p>Could not find Messages database at {MESSAGES_DB}. "
            "Have you used Messages on this Mac?</p>"
        )

    try:
        # Work on a copy so Messages.app isn't disturbed
        copy_database(MESSAGES_DB, TEMP_DB)
        conn = sqlite3.connect(str(TEMP_DB))
        contact_names = load_contact_names()
        handle_names, chat_info = load_handles_and_chats(conn, contact_names)
        messages = load_messages(conn, handle_names, chat_info)
        conn.close()
    finally:
        # Clean up temp DB
        if TEMP_DB.exists():
            try:
                TEMP_DB.unlink()
            except Exception:
                pass

    # All Time = all messages
    messages_all = messages[:]

    # Yearly stats for years 2021–2025 if they exist
    years = sorted({m["datetime"].year for m in messages_all if m["datetime"].year >= 2021})
    stats_total = compute_stats(messages_all, top_n=15)

    stats_by_year_dict = {}
    for y in years:
        msgs_for_year = [m for m in messages_all if m["datetime"].year == y]
        stats_y = compute_stats(msgs_for_year, top_n=10)
        stats_by_year_dict[str(y)] = stats_y

    # Build list for template (year, stats)
    stats_by_year_list = [
        (year, stats_by_year_dict[year])
        for year in sorted(stats_by_year_dict.keys(), reverse=True)
    ]

    # Dropdown order: 2025, 2024, 2023, 2022, 2021, All Time
    ordered_years = ["2025", "2024", "2023", "2022", "2021"]

    period_labels = []
    for y in ordered_years:
        if y in stats_by_year_dict:
            period_labels.append((y, f"{y} Wrapped"))
    period_labels.append(("all", "All Time"))

    # Default period: newest year available, else all
    default_period = "all"
    for y in ordered_years:
        if y in stats_by_year_dict:
            default_period = y
            break

    return render_template_string(
        TEMPLATE,
        stats_total=stats_total,
        stats_by_year=stats_by_year_list,
        period_labels=period_labels,
        default_period=default_period,
    )


if __name__ == "__main__":
    import webbrowser
    import threading
    import socket
    
    def find_free_port():
        """Find an available port starting from 5001"""
        for port in range(5001, 5100):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(("127.0.0.1", port))
                    return port
            except OSError:
                continue
        return 5001  # Fallback
    
    port = find_free_port()
    
    def open_browser():
        """Open browser after a short delay to ensure server is running"""
        import time
        time.sleep(1.5)
        webbrowser.open(f"http://127.0.0.1:{port}")
    
    # Start browser in a separate thread
    threading.Thread(target=open_browser, daemon=True).start()
    
    # Run Flask app
    print(f"Starting iMessage Wrapped on http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)