#!/usr/bin/env python3
"""Telegram bridge for the agent ticket loop (see docs/superpowers/specs/2026-06-10-ticket-loop-design.md).

Subcommands:
  send [--ticket NIP-123] <text...>   Send a message to the agent group; prints {"message_id": N}.
                                      With --ticket, records message_id -> ticket so a Telegram
                                      reply to that message matches the ticket on poll.
  poll [--timeout N]                  Long-poll getUpdates (default 25s); prints one JSON line per
                                      new human message in the agent group:
                                      {message_id, from, text, ticket, reply_to_message_id}
                                      `ticket` is resolved from a reply-to question or a NIP-### prefix.
  discover                            Print every chat the bot has recently seen (id, type, title) —
                                      use to grab a new group's chat id. Does not consume updates.

Env (from the environment or repo-root .env): TELEGRAM_BOT_TOKEN, AGENT_TELEGRAM_CHAT_ID.
State: .local/agent-loop/state.json  {offset, questions: {message_id: "NIP-123"}}.
Stdlib only — runs under any python3.
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = REPO_ROOT / ".local" / "agent-loop" / "state.json"
TICKET_RE = re.compile(r"^\s*(NIP-\d+)\b", re.IGNORECASE)


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
        sys.exit(f"error: {name} is not set (add it to .env — see deploy/env.example)")
    return value


def api(method: str, params: dict, *, http_timeout: int = 35) -> dict:
    token = require_env("TELEGRAM_BOT_TOKEN")
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params).encode()
    try:
        with urllib.request.urlopen(url, data=data, timeout=http_timeout) as resp:
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


def match_ticket(msg: dict, questions: dict):
    """Return the issue key (e.g. NIP-123) this message answers, or None."""
    reply = msg.get("reply_to_message") or {}
    via_reply = questions.get(str(reply.get("message_id")))
    if via_reply:
        return via_reply
    prefix = TICKET_RE.match(msg.get("text") or "")
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
        })
    # Crash-recovery affordance: the batch is persisted before the offset commit,
    # so a consumer that dies mid-processing can re-read what the advanced offset
    # would otherwise have swallowed.
    batch_path = STATE_PATH.parent / "last-batch.json"
    batch_path.write_text(json.dumps(emitted, ensure_ascii=False, indent=2) + "\n")
    save_state(state)
    for line in emitted:
        print(json.dumps(line, ensure_ascii=False))


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

    p_disc = sub.add_parser("discover", help="print chats the bot has recently seen")
    p_disc.set_defaults(func=cmd_discover)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
