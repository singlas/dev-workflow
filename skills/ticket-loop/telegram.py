#!/usr/bin/env python3
"""Telegram bridge for the ticket-loop skill.

Subcommands:
  send [--ticket ABC-123] <text...>   Send a message to the agent group; prints {"message_id": N}.
                                      With --ticket, records message_id -> ticket so a Telegram
                                      reply to that message matches the ticket on poll.
  poll [--timeout N]                  Long-poll getUpdates (default 25s); prints one JSON line per
                                      new human message in the agent group:
                                      {message_id, from, from_id, text, ticket, reply_to_message_id, media_path}
                                      `ticket` is resolved from a reply-to question or an ABC-### prefix
                                      (any Linear-style TEAM-123 key matches).
                                      Photos (and image documents) are downloaded to
                                      <repo>/.agent-loop/media/<message_id>.<ext>; `media_path` carries
                                      the local path (null for text-only messages), `text` the caption.
  send-photo [--ticket ABC-123] [--caption TEXT] <path>
                                      Send an image file to the agent group; prints {"message_id": N}.
  send-document [--caption TEXT] <path>
                                      Send a file (e.g. a PDF report) to the agent group; prints {"message_id": N}.
  discover                            Print every chat the bot has recently seen (id, type, title) —
                                      use to grab a new group's chat id. Does not consume updates.

Env (from the environment or repo-root .env): TELEGRAM_BOT_TOKEN, AGENT_TELEGRAM_CHAT_ID.
State dir: <repo>/.agent-loop by default; override with TICKET_LOOP_STATE_DIR (an
absolute path, or one relative to the repo root). Holds state.json
{offset, questions: {message_id: "ABC-123"}} + downloaded media — gitignore it.
Stdlib only — runs under any python3.
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def find_repo_root() -> Path:
    """Walk up from the script (then cwd) to the nearest directory containing .git."""
    for base in (Path(__file__).resolve().parent, Path.cwd()):
        for candidate in (base, *base.parents):
            if (candidate / ".git").exists():
                return candidate
    return Path.cwd()


def state_dir() -> Path:
    """The loop's state dir: TICKET_LOOP_STATE_DIR (absolute, or relative to the
    repo root) when set, else <repo>/.agent-loop. Keeps the runner, the lock, and
    this bridge pointed at the same directory across laptop + container layouts."""
    override = os.environ.get("TICKET_LOOP_STATE_DIR", "").strip()
    if override:
        p = Path(override)
        return p if p.is_absolute() else (REPO_ROOT / p)
    return REPO_ROOT / ".agent-loop"


REPO_ROOT = find_repo_root()
STATE_PATH = state_dir() / "state.json"
TICKET_RE = re.compile(r"^\s*([A-Z][A-Z0-9]*-\d+)\b", re.IGNORECASE)


def load_env() -> None:
    """Load repo-root .env into os.environ without overriding existing vars."""
    import os

    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        os.environ.setdefault(key, value)


def require_env(name: str) -> str:
    import os

    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"error: {name} is not set (add it to your repo-root .env — see env.example next to this script)")
    return value


def api(method: str, params: dict, *, http_timeout: int = 35) -> dict:
    return _request(method, urllib.parse.urlencode(params).encode(), {}, http_timeout)


def _request(method: str, data: bytes, headers: dict, http_timeout: int) -> dict:
    token = require_env("TELEGRAM_BOT_TOKEN")
    url = f"https://api.telegram.org/bot{token}/{method}"
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=http_timeout) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as exc:
        sys.exit(f"error: telegram {method} failed: HTTP {exc.code} {exc.read().decode(errors='replace')[:300]}")
    except (urllib.error.URLError, TimeoutError) as exc:
        sys.exit(f"error: telegram {method} unreachable: {exc}")
    if not payload.get("ok"):
        sys.exit(f"error: telegram {method} failed: {payload.get('description')}")
    return payload["result"]


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except json.JSONDecodeError:
            sys.exit(f"error: {STATE_PATH} is corrupt — inspect/fix it (offset + questions map), "
                     "or delete it to restart from Telegram's current backlog")
    return {"offset": 0, "questions": {}}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n")
    tmp.replace(STATE_PATH)  # atomic — a crash mid-write can't corrupt the state file


def cmd_send(args: argparse.Namespace) -> None:
    chat_id = require_env("AGENT_TELEGRAM_CHAT_ID")
    text = " ".join(args.text).strip() or sys.stdin.read().strip()
    if not text:
        sys.exit("error: empty message")
    result = api("sendMessage", {"chat_id": chat_id, "text": text})
    message_id = result["message_id"]
    if args.ticket:
        state = load_state()
        state.setdefault("questions", {})[str(message_id)] = args.ticket.upper()
        save_state(state)
    print(json.dumps({"message_id": message_id}))


def download_media(msg: dict):
    """Download a photo (or image document) attached to msg; return the local path or None.

    A failed download degrades to a warning — the poll batch must still emit the
    message (with its caption) rather than die on a transient file fetch.
    """
    photo = msg.get("photo")
    doc = msg.get("document") or {}
    if photo:
        file_id = photo[-1]["file_id"]  # PhotoSize list is ordered smallest → largest
    elif str(doc.get("mime_type") or "").startswith("image/"):
        file_id = doc["file_id"]
    else:
        return None
    token = require_env("TELEGRAM_BOT_TOKEN")
    try:
        remote = api("getFile", {"file_id": file_id}).get("file_path") or ""
        ext = Path(remote).suffix or ".jpg"
        dest = STATE_PATH.parent / "media" / f"{msg['message_id']}{ext}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://api.telegram.org/file/bot{token}/{remote}"
        with urllib.request.urlopen(url, timeout=60) as resp:
            dest.write_bytes(resp.read())
        return str(dest)
    except (Exception, SystemExit) as exc:
        print(f"warning: media download failed for message {msg.get('message_id')}: {exc}", file=sys.stderr)
        return None


def match_ticket(msg: dict, questions: dict):
    """Return the issue key (e.g. ABC-123) this message answers, or None."""
    reply = msg.get("reply_to_message") or {}
    via_reply = questions.get(str(reply.get("message_id")))
    if via_reply:
        return via_reply
    prefix = TICKET_RE.match(msg.get("text") or msg.get("caption") or "")
    return prefix.group(1).upper() if prefix else None


def cmd_poll(args: argparse.Namespace) -> None:
    chat_id = require_env("AGENT_TELEGRAM_CHAT_ID")
    state = load_state()
    questions = state.setdefault("questions", {})
    updates = api(
        "getUpdates",
        {"offset": state.get("offset", 0), "timeout": args.timeout, "allowed_updates": '["message"]'},
        http_timeout=args.timeout + 15,
    )
    emitted = []
    for update in updates:
        state["offset"] = update["update_id"] + 1
        msg = update.get("message")
        if not msg or str(msg.get("chat", {}).get("id")) != chat_id:
            continue
        sender = msg.get("from", {})
        if sender.get("is_bot"):
            continue
        ticket = match_ticket(msg, questions)
        if ticket:
            # A reply consumes the question entry; a follow-up question re-records it.
            reply_id = str((msg.get("reply_to_message") or {}).get("message_id"))
            questions.pop(reply_id, None)
        emitted.append({
            "message_id": msg["message_id"],
            # username is display-level; from_id is the stable identity — record
            # from_id in any audit trail (e.g. mirrored Linear comments).
            "from": sender.get("username") or sender.get("first_name") or "unknown",
            "from_id": sender.get("id"),
            "text": msg.get("text") or (msg.get("caption") or ""),
            "ticket": ticket,
            "reply_to_message_id": (msg.get("reply_to_message") or {}).get("message_id"),
            "media_path": download_media(msg),
        })
    # Crash-recovery affordance: the batch is persisted before the offset commit,
    # so a consumer that dies mid-processing can re-read what the advanced offset
    # would otherwise have swallowed.
    batch_path = STATE_PATH.parent / "last-batch.json"
    batch_path.parent.mkdir(parents=True, exist_ok=True)
    batch_path.write_text(json.dumps(emitted, ensure_ascii=False, indent=2) + "\n")
    save_state(state)
    for line in emitted:
        print(json.dumps(line, ensure_ascii=False))


def cmd_send_photo(args: argparse.Namespace) -> None:
    import uuid

    chat_id = require_env("AGENT_TELEGRAM_CHAT_ID")
    path = Path(args.path)
    if not path.is_file():
        sys.exit(f"error: {path} is not a file")
    boundary = uuid.uuid4().hex
    parts = []
    fields = {"chat_id": chat_id}
    if args.caption:
        fields["caption"] = args.caption
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="{path.name}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n".encode()
    )
    parts.append(path.read_bytes())
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    result = _request(
        "sendPhoto",
        b"".join(parts),
        {"Content-Type": f"multipart/form-data; boundary={boundary}"},
        http_timeout=60,
    )
    message_id = result["message_id"]
    if args.ticket:
        state = load_state()
        state.setdefault("questions", {})[str(message_id)] = args.ticket.upper()
        save_state(state)
    print(json.dumps({"message_id": message_id}))


def cmd_send_document(args: argparse.Namespace) -> None:
    """Send a file (e.g. a PDF report) to the agent group via sendDocument."""
    import uuid

    chat_id = require_env("AGENT_TELEGRAM_CHAT_ID")
    path = Path(args.path)
    if not path.is_file():
        sys.exit(f"error: {path} is not a file")
    boundary = uuid.uuid4().hex
    parts = []
    fields = {"chat_id": chat_id}
    if args.caption:
        fields["caption"] = args.caption
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{path.name}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n".encode()
    )
    parts.append(path.read_bytes())
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    result = _request(
        "sendDocument",
        b"".join(parts),
        {"Content-Type": f"multipart/form-data; boundary={boundary}"},
        http_timeout=120,
    )
    print(json.dumps({"message_id": result["message_id"]}))


def cmd_discover(_args: argparse.Namespace) -> None:
    updates = api("getUpdates", {"timeout": 0}, http_timeout=15)
    seen = {}
    for update in updates:
        chat = (update.get("message") or update.get("my_chat_member") or {}).get("chat")
        if chat:
            seen[chat["id"]] = {"id": chat["id"], "type": chat.get("type"),
                                "title": chat.get("title") or chat.get("username") or ""}
    if not seen:
        print("no recent updates — send a message in the target group (with the bot added) and rerun",
              file=sys.stderr)
    for chat in seen.values():
        print(json.dumps(chat, ensure_ascii=False))


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_send = sub.add_parser("send", help="send a message to the agent group")
    p_send.add_argument("--ticket", help="issue key this question belongs to (records reply matching)")
    p_send.add_argument("text", nargs="*", help="message text (or pipe via stdin)")
    p_send.set_defaults(func=cmd_send)

    p_poll = sub.add_parser("poll", help="fetch new messages from the agent group")
    p_poll.add_argument("--timeout", type=int, default=25, help="long-poll seconds (0 = instant)")
    p_poll.set_defaults(func=cmd_poll)

    p_photo = sub.add_parser("send-photo", help="send an image file to the agent group")
    p_photo.add_argument("--ticket", help="issue key this image belongs to (records reply matching)")
    p_photo.add_argument("--caption", help="caption to send with the image")
    p_photo.add_argument("path", help="path to the image file")
    p_photo.set_defaults(func=cmd_send_photo)

    p_doc = sub.add_parser("send-document", help="send a file (e.g. a PDF) to the agent group")
    p_doc.add_argument("--caption", help="caption to send with the document")
    p_doc.add_argument("path", help="path to the file to send")
    p_doc.set_defaults(func=cmd_send_document)

    p_disc = sub.add_parser("discover", help="print chats the bot has recently seen")
    p_disc.set_defaults(func=cmd_discover)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
