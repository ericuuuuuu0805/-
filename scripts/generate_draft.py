#!/usr/bin/env python3
"""
Main script: Fetches data from Notion + Gmail, generates weekly Slack update draft.
Runs every Friday at 11:00 AM JST via GitHub Actions.
Saves draft to drafts/weekly_update_YYYY-MM-DD.md for human review in Claude Code.
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def main():
    notion_api_key = os.environ.get("NOTION_API_KEY", "")
    projects_db_id = os.environ.get("NOTION_PROJECTS_DB_ID", "")
    meeting_db_id = os.environ.get("NOTION_MEETING_NOTES_DB_ID", "")

    if not all([notion_api_key, projects_db_id, meeting_db_id]):
        print("ERROR: Missing Notion environment variables.")
        print("Required: NOTION_API_KEY, NOTION_PROJECTS_DB_ID, NOTION_MEETING_NOTES_DB_ID")
        sys.exit(1)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY is not set.")
        sys.exit(1)

    print("=== 週次案件アップデート下書き生成 ===")
    print("1/3 Notionからデータ取得中...")

    from notion_fetcher import build_notion_context
    notion_data = build_notion_context(notion_api_key, projects_db_id, meeting_db_id)

    print(f"   - 今週更新された案件: {len(notion_data['week_projects'])}件")
    print(f"   - 動きなし案件: {len(notion_data['inactive_projects'])}件")
    print(f"   - 今週の議事録: {len(notion_data['meeting_notes'])}件")

    print("2/3 Gmailからメール取得中...")
    from gmail_fetcher import fetch_week_emails

    project_names = []
    for p in notion_data["week_projects"]:
        for key in ("名前", "案件名", "Name", "title"):
            if key in p:
                project_names.append(p[key])
                break

    gmail_data = fetch_week_emails(project_names=project_names)
    print(f"   - 今週の関連メール: {len(gmail_data)}件")

    print("3/3 Claude APIで下書き生成中...")
    from claude_summarizer import generate_weekly_update, build_date_range
    draft_text = generate_weekly_update(notion_data, gmail_data)

    JST = timezone(timedelta(hours=9))
    today = datetime.now(JST).strftime("%Y-%m-%d")
    _, _, date_str = build_date_range()

    drafts_dir = Path(__file__).parent.parent / "drafts"
    drafts_dir.mkdir(exist_ok=True)
    draft_path = drafts_dir / f"weekly_update_{today}.md"

    header = f"""# 週次案件アップデート下書き

**生成日時**: {datetime.now(JST).strftime('%Y年%m月%d日 %H:%M')} JST
**ステータス**: 承認待ち

---承認方法---
Claude Codeで以下を実行:
`このファイルの内容でSlackに投稿してください`

---

"""
    draft_path.write_text(header + draft_text, encoding="utf-8")

    print(f"\n下書きを保存しました: {draft_path}")
    print("\n" + "=" * 60)
    print(draft_text)
    print("=" * 60)

    # Send notification to Slack DM if configured
    slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
    notify_user = os.environ.get("SLACK_NOTIFY_USER_ID", "")
    if slack_token and notify_user:
        try:
            from slack_sdk import WebClient
            client = WebClient(token=slack_token)
            client.chat_postMessage(
                channel=notify_user,
                text=(
                    f"📝 *今週の案件アップデート下書きが生成されました*\n\n"
                    f"ファイル: `drafts/weekly_update_{today}.md`\n\n"
                    f"Claude Codeでレビューして承認後に投稿してください。\n"
                    f"承認コマンド例: `今週の下書きをレビューして投稿の準備をして`"
                )
            )
            print("Slack通知を送信しました")
        except Exception as e:
            print(f"Slack通知の送信に失敗: {e}")

    print("\n✅ 下書き生成完了。Claude Codeで確認・承認後に投稿してください。")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    main()
