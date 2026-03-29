# -*- coding: utf-8 -*-
"""Bilibili Direct Messages — read & reply via Web API.

Uses the bilibili account JSON (biliup format) for cookie auth.
No browser required — pure requests-based implementation.
"""

from __future__ import annotations

import json
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests

from utils.log import bilibili_logger

BILIBILI_NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
BILIBILI_SESSIONS_URL = "https://api.vc.bilibili.com/session_svr/v1/session_svr/get_sessions"
BILIBILI_FETCH_MSGS_URL = "https://api.vc.bilibili.com/svr_sync/v1/svr_sync/fetch_session_msgs"
BILIBILI_SEND_MSG_URL = "https://api.vc.bilibili.com/web_im/v1/web_im/send_msg"
BILIBILI_USER_INFO_URL = "https://api.bilibili.com/x/space/wbi/acc/info"

_DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_DEFAULT_HEADERS = {
    "User-Agent": _DEFAULT_UA,
    "Referer": "https://message.bilibili.com/",
    "Origin": "https://message.bilibili.com",
}


def _msg(emoji: str, text: str) -> str:
    return f"{emoji} {text}"


# ─── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class Conversation:
    """A conversation session in the DM list."""
    index: int
    talker_id: int
    talker_name: str
    last_message: str
    unread_count: int
    timestamp: int

    @property
    def is_unread(self) -> bool:
        return self.unread_count > 0


@dataclass
class Message:
    """A single message in a conversation."""
    sender: str        # "我" or talker_name
    sender_uid: int
    text: str
    msg_type: int
    timestamp: int


@dataclass
class ConversationDetail:
    """Full conversation detail with messages."""
    talker_id: int
    talker_name: str
    messages: list[Message] = field(default_factory=list)


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _load_cookies(account_file: str) -> dict[str, str]:
    """Load cookies from biliup account JSON."""
    path = Path(account_file)
    if not path.exists():
        raise RuntimeError(
            f"Cookie 文件不存在: {account_file}。"
            "请先运行 `sau bilibili login --account <name>`"
        )
    with path.open() as f:
        data = json.load(f)

    cookie_list = data.get("cookie_info", {}).get("cookies", [])
    return {c["name"]: c["value"] for c in cookie_list}


def _get_my_uid(cookies: dict) -> int:
    """Fetch logged-in user's UID."""
    r = requests.get(BILIBILI_NAV_URL, cookies=cookies, headers=_DEFAULT_HEADERS, timeout=10)
    r.raise_for_status()
    nav = r.json()
    if nav.get("code") != 0:
        raise RuntimeError(f"获取用户信息失败 (code={nav.get('code')}): {nav.get('message')}")
    return nav["data"]["mid"]


def _get_user_name(uid: int, cookies: dict) -> str:
    """Fetch username for a UID (best-effort, returns uid string on failure)."""
    try:
        r = requests.get(
            f"https://api.bilibili.com/x/space/acc/info",
            params={"mid": uid},
            cookies=cookies,
            headers=_DEFAULT_HEADERS,
            timeout=8,
        )
        data = r.json()
        if data.get("code") == 0:
            return data["data"].get("name", str(uid))
    except Exception:
        pass
    return str(uid)


def _parse_msg_text(msg: dict) -> str:
    """Parse raw message content into display text."""
    msg_type = msg.get("msg_type", 0)
    content_raw = msg.get("content", "{}")
    try:
        content = json.loads(content_raw)
    except Exception:
        return content_raw[:200]

    if msg_type == 1:
        return content.get("content", "")
    elif msg_type == 2:
        return "[图片]"
    elif msg_type == 5:
        return "[撤回了一条消息]"
    elif msg_type == 10:
        # System / notification message
        return content.get("text", content.get("title", "[系统消息]"))
    else:
        return f"[未知消息类型:{msg_type}]"


def _get_csrf(cookies: dict) -> str:
    """Extract CSRF token (bili_jct) from cookies."""
    csrf = cookies.get("bili_jct", "")
    if not csrf:
        raise RuntimeError("Cookie 中缺少 bili_jct (CSRF token)，请重新登录")
    return csrf


# ─── Core API functions ────────────────────────────────────────────────────────

def list_conversations(account_file: str) -> list[Conversation]:
    """List recent DM sessions. Returns most-recently-active first."""
    bilibili_logger.info(_msg("📬", "获取 B站私信会话列表"))
    cookies = _load_cookies(account_file)
    my_uid = _get_my_uid(cookies)
    bilibili_logger.info(_msg("👤", f"当前用户 UID: {my_uid}"))

    r = requests.get(
        BILIBILI_SESSIONS_URL,
        params={
            "session_type": 1,
            "group_fold": 1,
            "unfollow_fold": 0,
            "sort_rule": 2,
            "build": 0,
            "mobi_app": "web",
        },
        cookies=cookies,
        headers=_DEFAULT_HEADERS,
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()

    if data.get("code") != 0:
        raise RuntimeError(f"获取会话列表失败 (code={data.get('code')}): {data.get('message')}")

    session_list = data.get("data", {}).get("session_list", [])
    bilibili_logger.info(_msg("📋", f"共找到 {len(session_list)} 个会话"))

    conversations = []
    for idx, s in enumerate(session_list):
        talker_id = s.get("talker_id", 0)
        account_info = s.get("account_info", {})
        # account_info.name may be empty for some users; fall back to uid lookup
        talker_name = account_info.get("name") or str(talker_id)
        unread = s.get("unread_count", 0)
        ts = s.get("session_ts", 0)

        last_msg_raw = s.get("last_msg", {})
        last_text = _parse_msg_text(last_msg_raw)

        conversations.append(Conversation(
            index=idx,
            talker_id=talker_id,
            talker_name=talker_name,
            last_message=last_text,
            unread_count=unread,
            timestamp=ts,
        ))

    return conversations


def read_conversation(account_file: str, conversation_index: int) -> ConversationDetail:
    """Read full message history for the conversation at `conversation_index`."""
    cookies = _load_cookies(account_file)
    my_uid = _get_my_uid(cookies)

    convs = list_conversations(account_file)
    if conversation_index >= len(convs):
        raise RuntimeError(
            f"会话索引 {conversation_index} 超出范围 (共 {len(convs)} 个会话)"
        )

    conv = convs[conversation_index]
    bilibili_logger.info(_msg("💬", f"读取会话 [{conversation_index}] 与用户: {conv.talker_name}"))

    r = requests.get(
        BILIBILI_FETCH_MSGS_URL,
        params={
            "talker_id": conv.talker_id,
            "session_type": 1,
            "size": 50,
        },
        cookies=cookies,
        headers=_DEFAULT_HEADERS,
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()

    if data.get("code") != 0:
        raise RuntimeError(f"获取消息失败 (code={data.get('code')}): {data.get('message')}")

    raw_msgs = data.get("data", {}).get("messages", [])
    # Messages are returned oldest-first
    raw_msgs = sorted(raw_msgs, key=lambda m: m.get("timestamp", 0))

    detail = ConversationDetail(talker_id=conv.talker_id, talker_name=conv.talker_name)
    for m in raw_msgs:
        sender_uid = m.get("sender_uid", 0)
        is_me = (sender_uid == my_uid)
        text = _parse_msg_text(m)
        detail.messages.append(Message(
            sender="我" if is_me else conv.talker_name,
            sender_uid=sender_uid,
            text=text,
            msg_type=m.get("msg_type", 0),
            timestamp=m.get("timestamp", 0),
        ))

    bilibili_logger.info(_msg("📨", f"共 {len(detail.messages)} 条消息"))
    return detail


def reply_to_conversation(
    account_file: str,
    conversation_index: int,
    reply_text: str,
) -> bool:
    """Send a text reply to the conversation at `conversation_index`."""
    cookies = _load_cookies(account_file)
    my_uid = _get_my_uid(cookies)
    csrf = _get_csrf(cookies)

    convs = list_conversations(account_file)
    if conversation_index >= len(convs):
        raise RuntimeError(
            f"会话索引 {conversation_index} 超出范围 (共 {len(convs)} 个会话)"
        )

    conv = convs[conversation_index]
    bilibili_logger.info(_msg("📤", f"回复会话 [{conversation_index}] 与用户: {conv.talker_name}"))

    payload = {
        "msg[sender_uid]": my_uid,
        "msg[receiver_id]": conv.talker_id,
        "msg[receiver_type]": 1,
        "msg[msg_type]": 1,
        "msg[content]": json.dumps({"content": reply_text}, ensure_ascii=False),
        "msg[msg_status]": 0,
        "msg[timestamp]": int(time.time()),
        "msg[new_face_version]": 0,
        "csrf": csrf,
        "csrf_token": csrf,
        "from_firework": 0,
    }

    r = requests.post(
        BILIBILI_SEND_MSG_URL,
        data=payload,
        cookies=cookies,
        headers={
            **_DEFAULT_HEADERS,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        timeout=15,
    )
    r.raise_for_status()
    result = r.json()

    if result.get("code") == 0:
        bilibili_logger.info(_msg("✅", f"消息发送成功 → {conv.talker_name}: {reply_text[:50]}"))
        return True
    else:
        bilibili_logger.error(
            _msg("❌", f"消息发送失败 (code={result.get('code')}): {result.get('message')}")
        )
        return False
