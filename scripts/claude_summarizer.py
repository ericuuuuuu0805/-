"""Uses Claude API to generate a structured weekly Slack update from Notion and Gmail data."""

import json
from datetime import datetime, timedelta, timezone

import anthropic


JST = timezone(timedelta(hours=9))


SYSTEM_PROMPT = """あなたはビジネスプロジェクト管理アシスタントです。
毎週金曜日に、ノーション案件進捗データベース、議事録、Gmailのデータをもとに
Slackの「全案件アクティビティ」チャンネルへの投稿下書きを作成します。

以下のフォーマットで必ず出力してください。Slack投稿そのものの文章を出力してください。

---出力フォーマット---
📊 *今週の案件アップデート*（{date_range}）

━━━━━━━━━━━━━━━━━━━━
📂 *今週動きのあった案件*
━━━━━━━━━━━━━━━━━━━━

【案件名】
• *業種/業界*: （例: SaaS / HR Tech）
• *何があったか*: 具体的な出来事・進捗
• *誰と*: 関係者・担当者・商談相手
• *決定事項*: 今週決まったこと
• *ネクストアクション*:
  → （誰が）（いつまでに）（何をする）

（複数案件ある場合は繰り返し）

━━━━━━━━━━━━━━━━━━━━
📅 *今後2週間の予定*（{next_14_days}）
━━━━━━━━━━━━━━━━━━━━

• {date}: 【案件名】内容

（予定ある案件を日付順に列挙）

━━━━━━━━━━━━━━━━━━━━
🔇 *今週動きなし*: （案件名をカンマ区切り、なければ「なし」）
━━━━━━━━━━━━━━━━━━━━

_承認待ち — 投稿前に確認をお願いします_
---

ルール:
- 動きがなくても必ず投稿する
- 具体的な数字・固有名詞を使う
- 箇条書きで読みやすく
- 情報がない項目は「情報なし」ではなく省略する
- Slack のフォーマット（*太字*、_斜体_）を使う
"""


def build_date_range() -> tuple[str, str, str]:
    now = datetime.now(JST)
    monday = now - timedelta(days=now.weekday())
    date_range = f"{monday.strftime('%m/%d')}（月）〜 {now.strftime('%m/%d')}（金）"
    next_start = now + timedelta(days=1)
    next_end = now + timedelta(days=14)
    next_14_days = f"{next_start.strftime('%m/%d')} 〜 {next_end.strftime('%m/%d')}"
    return date_range, next_14_days, now.strftime("%Y-%m-%d")


def generate_weekly_update(notion_data: dict, gmail_data: list[dict], model: str = "claude-opus-4-8") -> str:
    client = anthropic.Anthropic()

    date_range, next_14_days, today = build_date_range()

    system = SYSTEM_PROMPT.format(date_range=date_range, next_14_days=next_14_days)

    user_content = f"""以下のデータをもとに、今週（{date_range}）の案件アップデートSlack投稿を作成してください。

=== 今週動きのあったノーション案件 ({len(notion_data['week_projects'])}件) ===
{json.dumps(notion_data['week_projects'], ensure_ascii=False, indent=2)}

=== 今週の議事録 ({len(notion_data['meeting_notes'])}件) ===
{json.dumps(notion_data['meeting_notes'], ensure_ascii=False, indent=2)}

=== 今週動きのなかった案件 ({len(notion_data['inactive_projects'])}件、名前のみ) ===
{json.dumps([{k: v for k, v in p.items() if k in ('名前', '案件名', 'Name', 'title')} for p in notion_data['inactive_projects']], ensure_ascii=False)}

=== 今週のGmail関連メール ({len(gmail_data)}件) ===
{json.dumps(gmail_data, ensure_ascii=False, indent=2)}

今後2週間（{next_14_days}）の予定も、ノーション案件データのスケジュール情報から抽出して含めてください。
"""

    message = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": user_content}]
    )

    return message.content[0].text
