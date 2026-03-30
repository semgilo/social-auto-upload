#!/usr/bin/env python3
import argparse
import asyncio
import json
import pathlib
import re
import sys
from dataclasses import dataclass
from datetime import datetime

import requests
from patchright.async_api import TimeoutError as PlaywrightTimeoutError
from patchright.async_api import async_playwright

sys.path.insert(0, "/Users/semgilo/.openclaw/tools/social-auto-upload")

from utils.base_social_media import set_init_script

DEFAULT_COOKIE_FILE = pathlib.Path(
    "/Users/semgilo/.openclaw/tools/social-auto-upload/cookies/bilibili_uploader/account.json"
)
DEFAULT_CATEGORY = "人工智能"
DEFAULT_SUBTITLE_LANG = "zh"
DEFAULT_FAILURE_SCREENSHOT = pathlib.Path(
    "/Users/semgilo/.openclaw/tools/social-auto-upload/data/bilibili_publish_failure.png"
)
UPLOAD_URL = "https://member.bilibili.com/york/videoup"
ARCHIVE_PRE_API = "https://member.bilibili.com/x/vupre/web/archive/pre?lang=cn"
ARCHIVES_API = (
    "https://member.bilibili.com/x/web/archives"
    "?status=is_pubing,pubed,not_pubed&pn=1&ps=10&interactive=1"
)
DRAFTS_API = "https://member.bilibili.com/x/vupre/web/draft/list"


@dataclass
class UploadConfig:
    cookie_file: pathlib.Path
    video_file: pathlib.Path
    subtitle_file: pathlib.Path | None
    title: str
    desc: str
    tags: list[str]
    category: str
    collection_name: str | None
    publish_time: datetime | None
    subtitle_lang: str
    headless: bool
    failure_screenshot: pathlib.Path

    @property
    def publish_date(self) -> str:
        if not self.publish_time:
            raise RuntimeError("publish_time 未设置")
        return self.publish_time.strftime("%Y-%m-%d")

    @property
    def publish_day(self) -> str:
        if not self.publish_time:
            raise RuntimeError("publish_time 未设置")
        return str(self.publish_time.day)

    @property
    def publish_hour(self) -> str:
        if not self.publish_time:
            raise RuntimeError("publish_time 未设置")
        return self.publish_time.strftime("%H")

    @property
    def publish_minute(self) -> str:
        if not self.publish_time:
            raise RuntimeError("publish_time 未设置")
        return self.publish_time.strftime("%M")


CONFIG: UploadConfig | None = None


def cfg() -> UploadConfig:
    if CONFIG is None:
        raise RuntimeError("上传配置尚未初始化")
    return CONFIG


def log(message: str) -> None:
    print(message, flush=True)


def parse_tags(raw_tags: str) -> list[str]:
    raw_parts = [part.strip() for part in re.split(r"[,，\n]", raw_tags) if part.strip()]
    tags: list[str] = []
    seen: set[str] = set()
    for part in raw_parts:
        normalized = re.sub(r"^#+", "", part).strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        tags.append(normalized)
    if not tags:
        raise ValueError("至少需要一个标签")
    return tags


def parse_publish_time(raw_publish_time: str | None) -> datetime | None:
    if not raw_publish_time:
        return None
    return datetime.strptime(raw_publish_time, "%Y-%m-%d %H:%M")


def parse_args() -> UploadConfig:
    parser = argparse.ArgumentParser(description="Bilibili 官方创作中心自动上传脚本")
    parser.add_argument("--video", required=True, help="视频文件绝对路径")
    parser.add_argument("--title", required=True, help="视频标题")
    parser.add_argument("--desc", help="视频简介，默认等于标题")
    parser.add_argument("--tags", required=True, help="标签，使用逗号分隔")
    parser.add_argument("--publish-time", help="定时发布时间，格式 YYYY-MM-DD HH:MM")
    parser.add_argument("--subtitle", help="字幕文件路径，支持 .srt")
    parser.add_argument("--subtitle-lang", default=DEFAULT_SUBTITLE_LANG, help="字幕语言代码，默认 zh")
    parser.add_argument("--category", default=DEFAULT_CATEGORY, help="投稿页的人类可读一级分类，默认 人工智能")
    parser.add_argument("--collection", help="合集名称，账号需已开通合集权限")
    parser.add_argument("--cookie-file", default=str(DEFAULT_COOKIE_FILE), help="Bilibili Cookie 文件路径")
    parser.add_argument(
        "--failure-screenshot",
        default=str(DEFAULT_FAILURE_SCREENSHOT),
        help="失败截图输出路径",
    )
    parser.add_argument(
        "--headful",
        action="store_true",
        help="使用有头浏览器，默认 headless",
    )

    args = parser.parse_args()
    desc = args.desc if args.desc is not None else args.title
    return UploadConfig(
        cookie_file=pathlib.Path(args.cookie_file),
        video_file=pathlib.Path(args.video),
        subtitle_file=pathlib.Path(args.subtitle) if args.subtitle else None,
        title=args.title,
        desc=desc,
        tags=parse_tags(args.tags),
        category=args.category,
        collection_name=args.collection,
        publish_time=parse_publish_time(args.publish_time),
        subtitle_lang=args.subtitle_lang,
        headless=not args.headful,
        failure_screenshot=pathlib.Path(args.failure_screenshot),
    )


def validate_config(config: UploadConfig) -> None:
    if not config.cookie_file.exists():
        raise FileNotFoundError(f"Cookie 文件不存在: {config.cookie_file}")
    if not config.video_file.exists():
        raise FileNotFoundError(f"视频文件不存在: {config.video_file}")
    if config.subtitle_file and not config.subtitle_file.exists():
        raise FileNotFoundError(f"字幕文件不存在: {config.subtitle_file}")
    config.failure_screenshot.parent.mkdir(parents=True, exist_ok=True)


def build_cookies(raw_cookie_data: dict) -> list[dict]:
    cookies = []
    for cookie in raw_cookie_data["cookie_info"]["cookies"]:
        cookies.append(
            {
                "name": cookie["name"],
                "value": cookie["value"],
                "domain": ".bilibili.com",
                "path": "/",
                "expires": cookie["expires"],
                "httpOnly": bool(cookie["http_only"]),
                "secure": bool(cookie["secure"]),
                "sameSite": "Lax",
            }
        )
    return cookies


def build_cookie_dict(raw_cookie_data: dict) -> dict[str, str]:
    return {
        cookie["name"]: cookie["value"]
        for cookie in raw_cookie_data["cookie_info"]["cookies"]
    }


def build_requests_session(cookie_dict: dict[str, str]) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "referer": UPLOAD_URL,
            "origin": "https://member.bilibili.com",
            "user-agent": "Mozilla/5.0",
        }
    )
    session.cookies.update(cookie_dict)
    return session


async def dismiss_popovers(page) -> None:
    for text in ["知道了", "同意", "暂不考虑"]:
        locator = page.get_by_role("button", name=text)
        if await locator.count():
            try:
                if await locator.first.is_visible():
                    await locator.first.click(force=True)
                    await page.wait_for_timeout(300)
            except PlaywrightTimeoutError:
                continue


async def open_upload_page(page) -> None:
    await page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(5000)
    title_text = await page.locator("body").inner_text()
    if "上传视频" not in title_text:
        raise RuntimeError("Bilibili 投稿页未正常打开")


async def set_video(page) -> None:
    log(f"上传视频: {cfg().video_file}")
    await page.locator("input[type='file']").first.set_input_files(str(cfg().video_file))
    await page.locator("input[placeholder='请输入稿件标题']").wait_for(timeout=30000)
    await page.wait_for_timeout(2000)


async def fetch_member_json(page, url: str) -> dict | None:
    response = await page.evaluate(
        """async (requestUrl) => {
            const response = await fetch(requestUrl, { credentials: "include" });
            return {
                status: response.status,
                text: await response.text(),
            };
        }""",
        url,
    )
    if response["status"] != 200:
        return None
    try:
        return json.loads(response["text"])
    except json.JSONDecodeError:
        return None


def upload_subtitle_asset(session: requests.Session, cookie_dict: dict[str, str]) -> str:
    subtitle_file = cfg().subtitle_file
    if subtitle_file is None:
        raise RuntimeError("未提供字幕文件")

    with subtitle_file.open("rb") as subtitle_handle:
        response = session.post(
            "https://api.bilibili.com/x/upload/web/image",
            data={
                "bucket": "subtitle",
                "csrf": cookie_dict["bili_jct"],
                "content_type": "application/x-subrip",
            },
            files={
                "file": (
                    subtitle_file.name,
                    subtitle_handle,
                    "application/x-subrip",
                )
            },
            timeout=180,
        )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 0 or not payload.get("data", {}).get("location"):
        raise RuntimeError(f"字幕文件上传失败: {payload}")
    return payload["data"]["location"]


def presave_subtitle(
    session: requests.Session,
    cookie_dict: dict[str, str],
    aid: int,
    cid: int,
    subtitle_url: str,
) -> None:
    response = session.post(
        "https://api.bilibili.com/x/v2/dm/subtitle/draft/preSave",
        data={
            "oid": str(cid),
            "type": "1",
            "files": json.dumps(
                [{"lan": cfg().subtitle_lang, "url": subtitle_url}],
                ensure_ascii=False,
            ),
            "aid": str(aid),
            "csrf": cookie_dict["bili_jct"],
        },
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"字幕保存失败: {payload}")


def fetch_archives_payload(session: requests.Session) -> dict:
    response = session.get(ARCHIVES_API, timeout=60)
    response.raise_for_status()
    return response.json()


def fetch_archive_pre_payload(session: requests.Session) -> dict:
    response = session.get(ARCHIVE_PRE_API, timeout=60)
    response.raise_for_status()
    return response.json()


def is_collection_enabled(pre_payload: dict | None) -> bool:
    if not pre_payload:
        return False
    return bool(pre_payload.get("data", {}).get("season"))


def extract_archive_entry(archives_payload: dict | None) -> dict | None:
    if not archives_payload:
        return None

    archive_groups = []
    data = archives_payload.get("data", {})
    if isinstance(data.get("arc_audits"), list):
        archive_groups.extend(data["arc_audits"])
    if isinstance(data.get("archives"), list):
        archive_groups.extend(data["archives"])

    for item in archive_groups:
        archive = item.get("Archive", item)
        if archive.get("title") == cfg().title:
            return item
    return None


async def fill_title(page) -> None:
    log(f"填写标题: {cfg().title}")
    await page.locator("input[placeholder='请输入稿件标题']").fill(cfg().title)


async def select_category(page) -> None:
    log(f"选择分区: {cfg().category}")
    await page.locator(".video-human-type .select-controller").first.click(force=True)
    option = page.locator(
        f".human-type-list .drop-list-v2-item[title='{cfg().category}']"
    ).first
    await option.wait_for(timeout=5000)
    await option.click(force=True)
    await page.wait_for_timeout(500)


async def clear_existing_tags(page) -> None:
    close_buttons = page.locator(".label-item-v2-container .close")
    for _ in range(20):
        count = await close_buttons.count()
        if count == 0:
            return
        await close_buttons.first.click(force=True)
        await page.wait_for_timeout(250)


async def get_current_tags(page) -> list[str]:
    tags = []
    tag_nodes = page.locator("p.label-item-v2-content")
    for idx in range(await tag_nodes.count()):
        tag_text = (await tag_nodes.nth(idx).inner_text()).strip()
        if tag_text:
            tags.append(tag_text)
    return tags


async def wait_for_default_tags(page) -> None:
    for _ in range(16):
        if await get_current_tags(page):
            await page.wait_for_timeout(1000)
            return
        await page.wait_for_timeout(250)


async def fill_tags(page) -> None:
    log(f"填写标签: {', '.join(cfg().tags)}")
    await wait_for_default_tags(page)
    await clear_existing_tags(page)
    tag_input = page.locator("input[placeholder='按回车键Enter创建标签']").first
    added_tags: list[str] = []
    skipped_tags: list[str] = []

    for tag in cfg().tags:
        await tag_input.click(force=True)
        await tag_input.fill("")
        await tag_input.type(tag, delay=50)
        await tag_input.press("Enter")
        for _ in range(40):
            current_tags = await get_current_tags(page)
            if tag in current_tags:
                added_tags.append(tag)
                break
            await page.wait_for_timeout(250)
        else:
            skipped_tags.append(tag)
            log(f"警告：标签未成功添加，已跳过: {tag}")

    current_tags = await get_current_tags(page)
    confirmed_tags = [tag for tag in added_tags if tag in current_tags]
    missing_added_tags = [tag for tag in added_tags if tag not in current_tags]
    if missing_added_tags:
        raise RuntimeError(f"已添加标签后又缺失: {', '.join(missing_added_tags)}")
    if not confirmed_tags:
        raise RuntimeError("标签全部添加失败，终止投稿")
    if skipped_tags:
        log(f"已跳过不兼容标签: {', '.join(skipped_tags)}")


async def fill_desc(page) -> None:
    log("填写简介")
    editor = page.locator(".desc-container .ql-editor").first
    await editor.click(force=True)
    await page.keyboard.press("Meta+A")
    await page.keyboard.press("Backspace")
    await page.keyboard.type(cfg().desc)


async def set_collection(page) -> None:
    if not cfg().collection_name:
        return

    log(f"设置合集: {cfg().collection_name}")
    season_section = page.locator(".video-season").first
    await season_section.wait_for(timeout=5000)
    section_text = await season_section.inner_text()
    if "开通合集功能需满足权益中心等级达Lv2" in section_text:
        raise RuntimeError("当前账号未开通合集权限，无法加入合集")

    candidate_inputs = [
        season_section.locator("input[placeholder*='合集']").first,
        season_section.locator("input").first,
    ]
    candidate_triggers = [
        season_section.locator(".select-controller").first,
        season_section.get_by_text("请选择合集", exact=False).first,
        season_section.get_by_text("加入合集", exact=False).first,
        season_section.locator("[class*='select']").first,
    ]

    input_locator = None
    for locator in candidate_inputs:
        try:
            if await locator.count():
                input_locator = locator
                break
        except Exception:
            continue

    trigger_used = False
    if input_locator is not None:
        await input_locator.click(force=True)
        await input_locator.fill(cfg().collection_name)
        trigger_used = True

    if not trigger_used:
        for locator in candidate_triggers:
            try:
                if await locator.count():
                    await locator.click(force=True)
                    trigger_used = True
                    break
            except Exception:
                continue

    if not trigger_used:
        raise RuntimeError("未找到合集选择控件，请检查当前账号权限或页面结构")

    await page.wait_for_timeout(500)

    option_locators = [
        page.locator(f".drop-list-v2-item[title='{cfg().collection_name}']").first,
        page.get_by_text(cfg().collection_name, exact=True).first,
        page.get_by_text(cfg().collection_name, exact=False).first,
        page.locator("[role='option']", has_text=cfg().collection_name).first,
    ]
    for locator in option_locators:
        try:
            if await locator.count():
                await locator.click(force=True)
                await page.wait_for_timeout(500)
                section_text = await season_section.inner_text()
                if cfg().collection_name in section_text:
                    log("合集选择完成")
                    return
        except Exception:
            continue

    raise RuntimeError(f"未能在页面中选中合集: {cfg().collection_name}")


async def set_schedule(page) -> None:
    if cfg().publish_time is None:
        return

    log(f"设置定时发布: {cfg().publish_date} {cfg().publish_hour}:{cfg().publish_minute}")
    await page.locator(".time-container .switch-container").first.click(force=True)
    await page.wait_for_timeout(300)

    await page.locator(".date-picker-date").click(force=True)
    await page.wait_for_timeout(300)
    date_item = page.locator(
        ".date-picker-container .date-item",
        has_text=cfg().publish_day,
    ).first
    await date_item.wait_for(timeout=5000)
    await date_item.click(force=True)
    await page.wait_for_timeout(300)

    await page.locator(".date-picker-timer").click(force=True)
    await page.wait_for_timeout(300)
    hour_panel = page.locator(".time-picker-container .time-picker-panel-select-wrp").nth(0)
    minute_panel = page.locator(".time-picker-container .time-picker-panel-select-wrp").nth(1)
    await hour_panel.locator(
        "span.time-picker-panel-select-item:not(.time-select-disabled)",
        has_text=cfg().publish_hour,
    ).first.click(force=True)
    await minute_panel.locator(
        "span.time-picker-panel-select-item:not(.time-select-disabled)",
        has_text=cfg().publish_minute,
    ).first.click(force=True)
    await page.wait_for_timeout(500)


async def try_upload_subtitle(page) -> None:
    if cfg().subtitle_file is None:
        log("未提供字幕文件，跳过投稿页字幕控件")
        return

    log(f"尝试上传字幕: {cfg().subtitle_file}")
    try:
        await page.get_by_text("更多设置", exact=False).first.click(force=True)
        await page.wait_for_timeout(500)
        subtitle_inputs = page.locator("input[type='file']")
        if await subtitle_inputs.count() >= 3:
            await subtitle_inputs.nth(2).set_input_files(str(cfg().subtitle_file))
            await page.wait_for_timeout(1000)
            log("字幕文件已提交到页面输入控件")
        else:
            log("未检测到字幕文件输入控件，跳过投稿页字幕控件")
    except Exception as exc:
        log(f"字幕上传未确认成功，继续投稿: {exc}")


async def submit(page) -> None:
    log("提交稿件")
    submit_button = page.locator(".submit-add").first
    await submit_button.wait_for(timeout=5000)
    await submit_button.click(force=True, no_wait_after=True)
    await page.wait_for_timeout(1000)

    for confirm_text in ["确认", "确定"]:
        confirm = page.get_by_role("button", name=confirm_text)
        if await confirm.count():
            try:
                if await confirm.first.is_visible():
                    await confirm.first.click(force=True)
                    await page.wait_for_timeout(500)
            except PlaywrightTimeoutError:
                continue


def parse_upload_progress(body_text: str) -> str | None:
    progress_match = re.search(r"已经上传：([^\n]+)", body_text)
    percent_match = re.search(r"(\d{1,3})%", body_text)
    if not progress_match and not percent_match:
        return None
    progress_bits = []
    if progress_match:
        progress_bits.append(progress_match.group(1).strip())
    if percent_match:
        progress_bits.append(f"{percent_match.group(1)}%")
    return " | ".join(progress_bits)


async def wait_for_archive_creation(page) -> dict | None:
    archives_payload = await fetch_member_json(page, ARCHIVES_API)
    archive_entry = extract_archive_entry(archives_payload)
    if archive_entry:
        return {
            "source": "archives",
            "payload": archives_payload,
            "entry": archive_entry,
        }

    drafts_payload = await fetch_member_json(page, DRAFTS_API)
    if drafts_payload:
        serialized = json.dumps(drafts_payload, ensure_ascii=False)
        if cfg().title in serialized:
            return {"source": "drafts", "payload": drafts_payload}

    return None


async def wait_for_publish_result(page) -> bool:
    for tick in range(1800):
        await page.wait_for_timeout(1000)
        body_text = await page.locator("body").inner_text()
        archive_result = await wait_for_archive_creation(page)
        if archive_result:
            log(f"投稿成功，已在 {archive_result['source']} 接口中确认稿件: {cfg().title}")
            return True

        current_url = page.url
        if "upload-manager" in current_url or "稿件管理" in body_text or "投稿成功" in body_text:
            log(f"投稿成功，当前页面: {current_url}")
            return True

        if tick % 15 == 0:
            progress = parse_upload_progress(body_text)
            if progress:
                log(f"等待自动投稿完成，当前上传进度: {progress}")
            elif "等待视频上传完后会自动提交" in body_text:
                log("等待自动投稿完成，视频仍在上传中")

        if "等待视频上传完后会自动提交" in body_text or "提交中..." in body_text:
            continue

        if any(text in body_text for text in ["标题", "分区", "标签", "简介"]):
            continue
    return False


def attach_subtitle_to_archive(cookie_dict: dict[str, str], archive_result: dict) -> None:
    if cfg().subtitle_file is None:
        log("未提供字幕文件，跳过字幕补传")
        return

    archive_entry = archive_result.get("entry") or {}
    captions_count = archive_entry.get("captions_count", 0)
    if captions_count:
        log(f"字幕已存在，无需重复上传，当前数量: {captions_count}")
        return

    archive = archive_entry.get("Archive", {})
    aid = archive.get("aid")
    cid_list = archive_entry.get("cid_list") or []
    if not aid or not cid_list:
        raise RuntimeError("未找到字幕补传所需的 aid/cid")

    log("通过官方字幕接口补传字幕")
    session = build_requests_session(cookie_dict)
    subtitle_url = upload_subtitle_asset(session, cookie_dict)
    presave_subtitle(session, cookie_dict, aid=aid, cid=cid_list[0], subtitle_url=subtitle_url)
    refreshed_entry = extract_archive_entry(fetch_archives_payload(session))
    refreshed_count = (refreshed_entry or {}).get("captions_count", 0)
    if refreshed_count:
        log(f"字幕补传成功，当前字幕数量: {refreshed_count}")
        return
    raise RuntimeError("字幕接口调用成功，但未确认字幕数量更新")


async def main() -> int:
    validate_config(cfg())
    cookie_data = json.loads(cfg().cookie_file.read_text(encoding="utf-8"))
    cookies = build_cookies(cookie_data)
    cookie_dict = build_cookie_dict(cookie_data)
    session = build_requests_session(cookie_dict)
    pre_payload = fetch_archive_pre_payload(session)
    if cfg().collection_name and not is_collection_enabled(pre_payload):
        raise RuntimeError("当前账号未开通合集权限，官方接口返回 season=false，无法加入合集")

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=cfg().headless)
        context = await browser.new_context(viewport={"width": 1440, "height": 1200})
        context = await set_init_script(context)
        await context.add_cookies(cookies)
        page = await context.new_page()

        try:
            await open_upload_page(page)
            await dismiss_popovers(page)
            await set_video(page)
            await fill_title(page)
            await select_category(page)
            await fill_tags(page)
            await fill_desc(page)
            await set_schedule(page)
            await set_collection(page)
            await try_upload_subtitle(page)
            await submit(page)
            success = await wait_for_publish_result(page)
            archive_result = await wait_for_archive_creation(page) if success else None
            if archive_result:
                attach_subtitle_to_archive(cookie_dict, archive_result)
            await browser.close()
            if not success:
                raise RuntimeError("未在预期时间内确认投稿成功")
            return 0
        except Exception:
            try:
                await page.screenshot(path=str(cfg().failure_screenshot), full_page=True)
                log(f"失败截图已保存: {cfg().failure_screenshot}")
            except Exception:
                pass
            await browser.close()
            raise


if __name__ == "__main__":
    CONFIG = parse_args()
    raise SystemExit(asyncio.run(main()))
