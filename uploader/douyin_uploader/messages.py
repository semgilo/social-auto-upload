# -*- coding: utf-8 -*-
"""Douyin Creator Center — Direct Messages (read & reply).

Uses Patchright browser automation with existing cookie auth to interact
with the Douyin creator message center.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from patchright.async_api import Page, Playwright, async_playwright

from conf import LOCAL_CHROME_HEADLESS, LOCAL_CHROME_PATH
from uploader.douyin_uploader.main import cookie_auth, douyin_setup
from utils.base_social_media import set_init_script
from utils.log import douyin_logger

# Creator home — we'll navigate from here to messages
DOUYIN_CREATOR_HOME = "https://creator.douyin.com/creator-micro/home"
DOUYIN_DEBUG_DIR = Path("/tmp/douyin_im_debug")


def _msg(emoji: str, text: str) -> str:
    return f"{emoji} {text}"


def _ensure_debug_dir():
    DOUYIN_DEBUG_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class Conversation:
    """A conversation in the IM sidebar."""
    index: int
    name: str
    last_message: str
    time: str
    unread: bool = False


@dataclass
class Message:
    """A single message bubble inside a conversation."""
    sender: str  # "我" or contact name
    text: str
    time: str = ""


@dataclass
class ConversationDetail:
    """Full conversation with message history."""
    contact_name: str
    messages: list[Message] = field(default_factory=list)


async def _ensure_cookie(account_file: str) -> bool:
    """Validate cookie; raise if invalid."""
    if not os.path.exists(account_file):
        raise RuntimeError(f"Cookie 文件不存在: {account_file}。请先运行 sau douyin login")
    if not await cookie_auth(account_file):
        raise RuntimeError(f"Cookie 已失效: {account_file}。请先运行 sau douyin login")
    return True


async def _navigate_to_im(page: Page, timeout: int = 20000) -> None:
    """Navigate to the IM / message page from creator home."""
    # Go to creator home first
    await page.goto(DOUYIN_CREATOR_HOME)
    await page.wait_for_load_state("networkidle", timeout=timeout)
    await asyncio.sleep(2)

    # Check if redirected to login
    if "login" in page.url or "passport" in page.url:
        raise RuntimeError("被重定向到登录页，Cookie 可能已失效")

    # Try to find and click "私信管理" link on the home page
    dm_link = page.get_by_text("私信管理", exact=False).first
    if await dm_link.count():
        douyin_logger.info(_msg("📬", "找到「私信管理」链接，正在点击"))
        await dm_link.click()
        await asyncio.sleep(3)
        await page.wait_for_load_state("networkidle", timeout=timeout)
        douyin_logger.info(_msg("📬", f"已跳转到: {page.url}"))
        return

    # Fallback: try left sidebar "互动管理" → expand → find message link
    interaction_menu = page.get_by_text("互动管理", exact=True).first
    if await interaction_menu.count():
        douyin_logger.info(_msg("📬", "展开「互动管理」菜单"))
        await interaction_menu.click()
        await asyncio.sleep(1)

        # Look for private message submenu item
        for text in ["私信", "私信管理", "消息管理", "私信消息"]:
            sub_item = page.get_by_text(text, exact=False).first
            if await sub_item.count():
                await sub_item.click()
                await asyncio.sleep(3)
                await page.wait_for_load_state("networkidle", timeout=timeout)
                douyin_logger.info(_msg("📬", f"已跳转到: {page.url}"))
                return

    # Final fallback: try direct IM URL patterns
    for im_url in [
        "https://creator.douyin.com/creator-micro/im",
        "https://creator.douyin.com/creator-micro/interact/message",
        "https://creator.douyin.com/creator-micro/interact/private-message",
    ]:
        douyin_logger.info(_msg("🔗", f"尝试直接访问: {im_url}"))
        await page.goto(im_url)
        await page.wait_for_load_state("networkidle", timeout=timeout)
        await asyncio.sleep(2)
        # Check if we're on a valid page (not redirected back to home)
        if page.url != DOUYIN_CREATOR_HOME and "login" not in page.url:
            douyin_logger.info(_msg("📬", f"到达页面: {page.url}"))
            return

    douyin_logger.warning(_msg("⚠️", f"未能进入私信页面，当前URL: {page.url}"))


async def _debug_screenshot(page: Page, label: str) -> str:
    """Take a debug screenshot and return the path."""
    _ensure_debug_dir()
    path = DOUYIN_DEBUG_DIR / f"{label}.png"
    await page.screenshot(path=str(path), full_page=True)
    douyin_logger.info(_msg("📸", f"截图已保存: {path}"))
    return str(path)


async def _dump_page_structure(page: Page, max_depth: int = 8) -> str:
    """Dump high-level DOM structure for debugging."""
    try:
        structure = await page.evaluate("""(maxDepth) => {
            function walk(el, depth) {
                if (depth > maxDepth) return '';
                const tag = el.tagName?.toLowerCase() || '';
                const cls = (el.className && typeof el.className === 'string')
                    ? el.className.split(' ').filter(c => c.length > 0 && c.length < 60).slice(0, 3).join('.')
                    : '';
                const directText = Array.from(el.childNodes)
                    .filter(n => n.nodeType === 3)
                    .map(n => n.textContent.trim())
                    .join(' ')
                    .substring(0, 40);
                const indent = '  '.repeat(depth);
                let result = '';
                if (tag) {
                    result = indent + '<' + tag + (cls ? '.' + cls : '') + '>' + (directText ? ' ' + directText : '') + '\\n';
                }
                for (const child of el.children || []) {
                    result += walk(child, depth + 1);
                }
                return result;
            }
            // Focus on the main content wrapper
            const main = document.querySelector('[class*="micro-wrapper"]') ||
                         document.querySelector('[class*="content-"]') ||
                         document.body;
            return walk(main, 0);
        }""", max_depth)
        return structure[:8000]
    except Exception as e:
        return f"(dump failed: {e})"


async def _extract_conversations(page: Page) -> list[Conversation]:
    """Extract the conversation list from the IM page.

    The page uses semi-design components with ReactVirtualized list.
    Selector: .semi-tabs-pane-active .semi-list-items li.semi-list-item
    """
    conversations: list[Conversation] = []

    # Wait for the list to render (ReactVirtualized needs a moment)
    await asyncio.sleep(3)

    # Use the correct semi-design + ReactVirtualized selectors
    raw = await page.evaluate("""() => {
        const results = [];
        const timePattern = /^(\\d{1,2}-\\d{1,2}|\\d{1,2}:\\d{1,2}|昨天|前天|刚刚|\\d+分钟前|\\d+小时前|星期[一二三四五六日])$/;

        // Target the active tab pane's list items
        const activePane = document.querySelector('.semi-tabs-pane-active');
        if (!activePane) return results;

        const listItems = activePane.querySelectorAll('li.semi-list-item');
        let index = 0;

        for (const item of listItems) {
            const fullText = (item.innerText || '').trim();
            if (!fullText || fullText === '没有更多了~') continue;

            const lines = fullText.split('\\n').map(l => l.trim()).filter(l => l.length > 0);

            let name = '';
            let lastMsg = '';
            let time = '';

            for (const line of lines) {
                if (timePattern.test(line)) {
                    time = line;
                } else if (!name) {
                    name = line;
                } else if (!lastMsg) {
                    lastMsg = line;
                }
            }

            if (!name && lines.length > 0) name = lines[0];
            if (!lastMsg && lines.length > 1) lastMsg = lines[lines.length - 1 !== 0 ? 1 : 1];

            // Check for unread badge
            const hasBadge = !!item.querySelector('[class*="badge"], [class*="unread"], [class*="dot"]');

            results.push({
                index: index++,
                name: name.substring(0, 50),
                last_message: lastMsg.substring(0, 100),
                time: time.substring(0, 20),
                unread: hasBadge,
            });
        }

        return results;
    }""")

    if raw:
        douyin_logger.info(_msg("📋", f"通过 JS 提取到 {len(raw)} 个会话"))
        for item in raw:
            conversations.append(Conversation(
                index=item["index"],
                name=item["name"],
                last_message=item["last_message"],
                time=item["time"],
                unread=item.get("unread", False),
            ))
    else:
        await _debug_screenshot(page, "no_conversations")
        # Deep DOM dump focusing on the tab content area
        deep_structure = await page.evaluate("""() => {
            function walk(el, depth) {
                if (depth > 12) return '';
                const tag = el.tagName?.toLowerCase() || '';
                const cls = (el.className && typeof el.className === 'string')
                    ? el.className.split(' ').filter(c => c.length > 0 && c.length < 60).slice(0, 3).join('.')
                    : '';
                const directText = Array.from(el.childNodes)
                    .filter(n => n.nodeType === 3)
                    .map(n => n.textContent.trim())
                    .filter(t => t.length > 0)
                    .join(' ')
                    .substring(0, 60);
                const indent = '  '.repeat(depth);
                let result = indent + '<' + tag + (cls ? '.' + cls : '') + '>';
                if (directText) result += ' ' + directText;
                result += '\\n';
                for (const child of el.children || []) {
                    result += walk(child, depth + 1);
                }
                return result;
            }
            // Target the tabs content area or the container
            const target = document.querySelector('.semi-tabs-content') ||
                           document.querySelector('[class*="container-"][class*="container-"]') ||
                           document.querySelector('[class*="micro-wrapper"]') ||
                           document.body;
            return walk(target, 0);
        }""")
        douyin_logger.warning(_msg("⚠️", f"未找到会话列表\n详细结构:\n{deep_structure[:5000]}"))

    return conversations


async def _click_conversation(page: Page, conversations: list[Conversation], index: int) -> bool:
    """Click on a conversation by its list index using Playwright native click.

    ReactVirtualized + semi-design needs native events (not JS click).
    """
    if index >= len(conversations):
        return False

    target_name = conversations[index].name
    url_before = page.url

    # Use Playwright's native locator to click (triggers React synthetic events)
    items = page.locator('.semi-tabs-pane-active li.semi-list-item')
    count = await items.count()
    douyin_logger.info(_msg("🔍", f"共找到 {count} 个 li.semi-list-item，要点击第 {index} 个"))

    if count <= index:
        douyin_logger.error(_msg("❌", f"列表项不足 {index + 1} 个"))
        return False

    await items.nth(index).click()
    await asyncio.sleep(4)
    try:
        await page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass

    url_after = page.url
    douyin_logger.info(_msg("👆", f"点击会话: {target_name} | URL: {url_before} → {url_after}"))
    return True


async def _extract_messages(page: Page, contact_name: str = "") -> ConversationDetail:
    """Extract messages from the currently open conversation's right panel."""
    detail = ConversationDetail(contact_name=contact_name)

    # Wait for chat panel to appear on the right side
    await asyncio.sleep(3)
    current_url = page.url
    douyin_logger.info(_msg("🔗", f"点击后URL: {current_url}"))
    await _debug_screenshot(page, "chat_panel")

    # Strategy: use JS to find messages in the RIGHT portion of the page
    # The sidebar is on the left (~250-300px), chat is on the right
    raw_msgs = await page.evaluate("""(contactName) => {
        const results = [];
        const seen = new Set();

        // Get sidebar boundary - look for the conversation list
        const sidebar = document.querySelector('.semi-tabs-pane-active');
        const sidebarRect = sidebar?.getBoundingClientRect();
        // Sidebar is typically ~280-320px wide
        const sidebarRight = sidebarRect ? (sidebarRect.right + 10) : 300;

        // Find all leaf text nodes in the right area
        // Emojis might be in img elements or span with special content
        const walker = document.createTreeWalker(
            document.body,
            NodeFilter.SHOW_ELEMENT,
            null,
            false
        );

        const elements = [];
        let node;
        while (node = walker.nextNode()) {
            const rect = node.getBoundingClientRect();
            if (rect.left < sidebarRight) continue;
            if (rect.top < 120 || rect.bottom > window.innerHeight - 120) continue;
            if (rect.width < 20 || rect.height < 10) continue;
            elements.push(node);
        }

        for (const el of elements) {
            // Get text content including alt text from images (for emojis)
            let text = '';

            // Direct text content
            const directText = el.innerText?.trim() || '';

            // Also check for img alt text (emojis are often images with alt)
            const imgs = el.querySelectorAll('img');
            const imgAlts = Array.from(imgs).map(img => img.alt).filter(Boolean).join('');

            // Combine
            text = directText || imgAlts;

            if (!text || text.length < 1) continue;
            if (text.length > 150) continue;
            if (seen.has(text)) continue;

            // Skip UI elements
            if (['发送', '关注', '查看Ta的主页', '在线客服', '抖音创作服务平台',
                 '新的创作', '高清发布', '数据中心', '互动管理', '私信管理'].includes(text)) continue;
            if (['首页', '活动管理', '内容管理', '变现中心', '创作中心'].includes(text)) continue;
            if (text === '没有更多了~') continue;
            // Skip if it looks like a username/header
            if (text === contactName || text === '陌生人消息') continue;

            seen.add(text);

            // Determine sender by horizontal position
            const rect = el.getBoundingClientRect();
            const chatAreaCenter = sidebarRight + (window.innerWidth - sidebarRight) / 2;
            const isSelf = rect.left > chatAreaCenter;

            results.push({
                sender: isSelf ? '我' : (contactName || '对方'),
                text: text,
                left: rect.left,
                top: rect.top,
            });
        }

        // Sort by vertical position (top to bottom)
        results.sort((a, b) => a.top - b.top);

        return { items: results.map(r => ({ sender: r.sender, text: r.text })), count: results.length };
    }""", contact_name)

    if isinstance(raw_msgs, dict) and raw_msgs.get("items") and len(raw_msgs["items"]) > 0:
        for m in raw_msgs["items"]:
            detail.messages.append(Message(
                sender=m.get("sender") or contact_name or "对方",
                text=m["text"],
            ))
        douyin_logger.info(_msg("💬", f"提取到 {len(detail.messages)} 条消息"))
        return detail
    else:
        douyin_logger.warning(_msg("⚠️", f"JS 消息提取结果: {raw_msgs}"))

    # Final fallback: just return empty, we've tried our best
    return detail


async def _send_reply(page: Page, text: str) -> bool:
    """Type and send a reply in the currently open conversation."""
    # Find the input area
    input_selectors = [
        '[class*="chat-input"] [contenteditable="true"]',
        '[class*="editor"] [contenteditable="true"]',
        '[class*="im-input"] [contenteditable="true"]',
        '[class*="reply-input"] [contenteditable="true"]',
        '[class*="input-area"] [contenteditable="true"]',
        '[contenteditable="true"]',
        'textarea[class*="input"]',
        'textarea[class*="chat"]',
        'textarea',
    ]

    input_el = None
    for selector in input_selectors:
        el = page.locator(selector).first
        if await el.count():
            try:
                if await el.is_visible():
                    input_el = el
                    douyin_logger.info(_msg("✏️", f"找到输入框 ({selector})"))
                    break
            except:
                pass

    if input_el is None:
        await _debug_screenshot(page, "no_input")
        douyin_logger.error(_msg("❌", "未找到输入框"))
        return False

    # Click and type
    await input_el.click()
    await asyncio.sleep(0.5)

    # Clear existing content
    try:
        await input_el.fill("")
    except:
        await page.keyboard.press("Control+KeyA")
        await page.keyboard.press("Delete")

    await page.keyboard.type(text)
    await asyncio.sleep(0.5)

    # Find and click send button, or press Enter
    send_selectors = [
        'button:has-text("发送")',
        '[class*="send-btn"]',
        '[class*="sendBtn"]',
        'button[class*="send"]',
        '[class*="send"][class*="button"]',
    ]

    sent = False
    for selector in send_selectors:
        btn = page.locator(selector).first
        if await btn.count():
            try:
                if await btn.is_visible():
                    await btn.click()
                    sent = True
                    douyin_logger.info(_msg("📤", "点击发送按钮"))
                    break
            except:
                pass

    if not sent:
        # Fallback: press Enter to send
        await page.keyboard.press("Enter")
        douyin_logger.info(_msg("📤", "按 Enter 发送"))
        sent = True

    await asyncio.sleep(1)
    return sent


# ─── Public API ───────────────────────────────────────────────

async def list_conversations(
    account_file: str,
    headless: bool = LOCAL_CHROME_HEADLESS,
) -> list[Conversation]:
    """List recent conversations from the IM page."""
    await _ensure_cookie(account_file)
    douyin_logger.info(_msg("📬", "正在打开抖音私信页面"))

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=headless, channel="chrome")
        context = await browser.new_context(storage_state=account_file)
        context = await set_init_script(context)
        try:
            page = await context.new_page()
            await _navigate_to_im(page)
            conversations = await _extract_conversations(page)

            await context.storage_state(path=account_file)
            return conversations
        finally:
            await context.close()
            await browser.close()


async def read_conversation(
    account_file: str,
    conversation_index: int = 0,
    headless: bool = LOCAL_CHROME_HEADLESS,
) -> ConversationDetail:
    """Open a conversation by index and read its messages."""
    await _ensure_cookie(account_file)
    douyin_logger.info(_msg("📬", f"正在打开第 {conversation_index} 个会话"))

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=headless, channel="chrome")
        context = await browser.new_context(storage_state=account_file)
        context = await set_init_script(context)
        try:
            page = await context.new_page()
            await _navigate_to_im(page)

            # First get the conversation list for the name
            conversations = await _extract_conversations(page)
            contact_name = ""
            if conversation_index < len(conversations):
                contact_name = conversations[conversation_index].name

            # Click into the conversation
            if not await _click_conversation(page, conversations, conversation_index):
                raise RuntimeError(f"无法点击第 {conversation_index} 个会话")

            detail = await _extract_messages(page, contact_name)

            await context.storage_state(path=account_file)
            return detail
        finally:
            await context.close()
            await browser.close()


async def reply_to_conversation(
    account_file: str,
    conversation_index: int,
    reply_text: str,
    headless: bool = LOCAL_CHROME_HEADLESS,
) -> bool:
    """Open a conversation by index and send a reply."""
    await _ensure_cookie(account_file)
    douyin_logger.info(_msg("💬", f"正在回复第 {conversation_index} 个会话"))

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=headless, channel="chrome")
        context = await browser.new_context(storage_state=account_file)
        context = await set_init_script(context)
        try:
            page = await context.new_page()
            await _navigate_to_im(page)

            conversations = await _extract_conversations(page)
            if not await _click_conversation(page, conversations, conversation_index):
                raise RuntimeError(f"无法点击第 {conversation_index} 个会话")

            success = await _send_reply(page, reply_text)
            if success:
                douyin_logger.success(_msg("✅", "消息发送成功"))
            else:
                douyin_logger.error(_msg("❌", "消息发送失败"))

            await context.storage_state(path=account_file)
            return success
        finally:
            await context.close()
            await browser.close()


async def read_and_reply(
    account_file: str,
    conversation_index: int,
    reply_text: str,
    headless: bool = LOCAL_CHROME_HEADLESS,
) -> tuple[ConversationDetail, bool]:
    """Read messages and reply in a single browser session."""
    await _ensure_cookie(account_file)
    douyin_logger.info(_msg("💬", f"正在读取并回复第 {conversation_index} 个会话"))

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=headless, channel="chrome")
        context = await browser.new_context(storage_state=account_file)
        context = await set_init_script(context)
        try:
            page = await context.new_page()
            await _navigate_to_im(page)

            # Get conversations
            conversations = await _extract_conversations(page)
            contact_name = ""
            if conversation_index < len(conversations):
                contact_name = conversations[conversation_index].name

            # Open conversation
            if not await _click_conversation(page, conversations, conversation_index):
                raise RuntimeError(f"无法点击第 {conversation_index} 个会话")

            # Read messages
            detail = await _extract_messages(page, contact_name)

            # Send reply
            success = await _send_reply(page, reply_text)
            if success:
                douyin_logger.success(_msg("✅", "消息发送成功"))

            await context.storage_state(path=account_file)
            return detail, success
        finally:
            await context.close()
            await browser.close()
