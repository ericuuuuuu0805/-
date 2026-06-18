#!/usr/bin/env python3
"""
Posts an approved weekly update draft to Slack.
Called by Claude Code after user approval.

Usage:
  python scripts/post_to_slack.py [--draft drafts/weekly_update_2026-06-20.md]
  python scripts/post_to_slack.py --latest   # Use most recent draft
  python scripts/post_to_slack.py --text "カスタムテキスト"
"""

import argparse
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()


def get_latest_draft() -> Path | None:
    drafts_dir = Path(__file__).parent.parent / "drafts"
    md_files = sorted(drafts_dir.glob("weekly_update_*.md"), reverse=True)
    return md_files[0] if md_files else None


def extract_slack_content(draft_path: Path) -> str:
    """Extract the Slack message content from the draft file (skip the header)."""
    content = draft_path.read_text(encoding="utf-8")
    # Skip the markdown header section (everything before the first '📊' or '---\n\n' after header)
    markers = ["📊", "━━", "📂"]
    for marker in markers:
        idx = content.find(marker)
        if idx > 0:
            return content[idx:]
    # Fallback: skip lines starting with #
    lines = content.split("\n")
    start = 0
    for i, line in enumerate(lines):
        if line.startswith("---") and i > 3:
            start = i + 2
            break
    return "\n".join(lines[start:]).strip()


def post_to_slack(text: str, channel_id: str, token: str) -> bool:
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError

    client = WebClient(token=token)
    try:
        response = client.chat_postMessage(
            channel=channel_id,
            text=text,
            mrkdwn=True,
        )
        print(f"✅ Slackに投稿しました (ts: {response['ts']})")
        return True
    except SlackApiError as e:
        print(f"❌ Slack投稿エラー: {e.response['error']}")
        return False


def main():
    parser = argparse.ArgumentParser(description="承認済みの下書きをSlackに投稿")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--draft", help="投稿する下書きファイルのパス")
    group.add_argument("--latest", action="store_true", help="最新の下書きを投稿")
    group.add_argument("--text", help="直接テキストを指定して投稿")
    args = parser.parse_args()

    token = os.environ.get("SLACK_BOT_TOKEN", "")
    channel_id = os.environ.get("SLACK_CHANNEL_ID", "")

    if not token:
        print("ERROR: SLACK_BOT_TOKEN が設定されていません")
        sys.exit(1)
    if not channel_id:
        print("ERROR: SLACK_CHANNEL_ID が設定されていません")
        sys.exit(1)

    if args.text:
        text = args.text
    elif args.draft:
        draft_path = Path(args.draft)
        if not draft_path.exists():
            print(f"ERROR: ファイルが見つかりません: {draft_path}")
            sys.exit(1)
        text = extract_slack_content(draft_path)
    else:
        draft_path = get_latest_draft()
        if not draft_path:
            print("ERROR: drafts/ フォルダに下書きファイルがありません")
            sys.exit(1)
        print(f"最新の下書きを使用: {draft_path.name}")
        text = extract_slack_content(draft_path)

    print("\n--- 投稿内容 ---")
    print(text)
    print("---------------\n")

    success = post_to_slack(text, channel_id, token)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    main()
