#!/usr/bin/env python3
import sys
import pathlib
import asyncio

sys.path.insert(0, '/Users/semgilo/.openclaw/tools/social-auto-upload')

from uploader.douyin_uploader.main import DouYinVideo

# 配置
COOKIE_FILE = '/Users/semgilo/.openclaw/tools/social-auto-upload/cookies/douyin_uploader/account.json'
VIDEO_FILE = '/Users/semgilo/Documents/git/VideoCut/runs/Rjd1LqF9cG4-gptoss-cosy-fix-silence/final_cn.mp4'
TITLE = '如何用OpenClaw Agents为你工作'
TAGS = ['OpenClaw', 'Agents', '工作流', 'AI自动化', '智能体']
# 封面图（可选，如果需要手动设置封面）
THUMBNAIL = ''  # 自动选择封面
# 明天 10:00
DTIME = 1773626400  # 2026-03-16 10:00:00

async def main():
    print(f"上传视频: {VIDEO_FILE}")
    print(f"标题: {TITLE}")
    print(f"标签: {TAGS}")
    print(f"封面: {THUMBNAIL if THUMBNAIL else '自动选择'}")
    print(f"定时: 2026-03-16 10:00")
    
    from datetime import datetime
    publish_date = datetime.fromtimestamp(DTIME)
    
    app = DouYinVideo(
        title=TITLE,
        file_path=VIDEO_FILE,
        tags=TAGS,
        publish_date=publish_date,
        account_file=COOKIE_FILE,
        thumbnail_path=THUMBNAIL,
    )
    
    await app.main()

if __name__ == '__main__':
    asyncio.run(main())
