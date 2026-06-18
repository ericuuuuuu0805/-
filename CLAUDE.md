# 週次案件アップデート - Claude Code ガイド

## このリポジトリの目的

毎週金曜日11時に、Notion案件進捗DB・議事録・Gmailのデータをもとに
Slackの「全案件アクティビティ」チャンネルへの週次アップデートを投稿するシステム。

**重要**: 投稿前に必ずユーザーの承認を得ること。承認なしには投稿しない。

---

## 週次フロー

### 1. 自動生成（毎週金曜 11:00 AM JST）
GitHub Actions が自動で下書きを生成し `drafts/weekly_update_YYYY-MM-DD.md` にコミット。

### 2. レビュー・承認（Claude Code）
ユーザーが下書きを確認。「この下書きをレビューして」と言えばOK。

### 3. 投稿（承認後のみ）
ユーザーが「承認、投稿してください」と言ったら投稿する。

---

## よく使うコマンド

```bash
# 下書きを手動生成（テスト用）
cd scripts && python generate_draft.py

# Slackに投稿（承認後のみ実行）
cd scripts && python post_to_slack.py --latest

# Gmail認証の初期設定（一度だけ実行）
python scripts/setup_gmail_auth.py --credentials /path/to/credentials.json
```

---

## 必要な GitHub Secrets

| Secret名 | 説明 |
|----------|------|
| `NOTION_API_KEY` | Notion Integration Token |
| `NOTION_PROJECTS_DB_ID` | 案件進捗データベースのID |
| `NOTION_MEETING_NOTES_DB_ID` | 議事録データベースのID |
| `GMAIL_TOKEN_JSON` | Gmail OAuth2トークン（setup_gmail_auth.pyで生成） |
| `ANTHROPIC_API_KEY` | Claude API Key |
| `SLACK_BOT_TOKEN` | Slack Bot Token (`xoxb-...`) |
| `SLACK_CHANNEL_ID` | 投稿先チャンネルID |
| `SLACK_NOTIFY_USER_ID` | 通知先ユーザーID（DM用） |

---

## Slack投稿フォーマット

```
📊 今週の案件アップデート（MM/DD（月）〜 MM/DD（金））

━━━━━━━━━━━━━━━━━━━━
📂 今週動きのあった案件
━━━━━━━━━━━━━━━━━━━━

【案件名】
• 業種/業界: ...
• 何があったか: ...
• 誰と: ...
• 決定事項: ...
• ネクストアクション:
  → （誰が）（いつまでに）（何をする）

━━━━━━━━━━━━━━━━━━━━
📅 今後2週間の予定（MM/DD 〜 MM/DD）
━━━━━━━━━━━━━━━━━━━━

• MM/DD: 【案件名】内容

━━━━━━━━━━━━━━━━━━━━
🔇 今週動きなし: 案件名A, 案件名B
━━━━━━━━━━━━━━━━━━━━
```
