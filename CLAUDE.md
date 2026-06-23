# 週次案件アップデート - Claude Code ガイド

## このリポジトリの目的

毎週金曜日11時に、Notion案件進捗DB・議事録・Gmailのデータをもとに
Slackの「全案件アクティビティ」チャンネルへの週次アップデートを投稿するシステム。

**重要**: 投稿前に必ずユーザーの承認を得ること。承認なしには投稿しない。

---

## 週次フロー

### 1. 自動実行（毎週金曜 11:00 AM JST）
GitHub Actions が `weekly_update_claude.yml` を起動。
Claude Code がウェブ版として自動起動し、Notion・Gmail からデータ取得 → 下書き生成 → Slack DM で通知。

### 2. レビュー・承認（Claude Code ウェブ版）
Slack DM で「下書きができました」と届いたら、Claude Code（ウェブ版）を開いて内容を確認。
「この下書きをレビューして」と入力すれば Claude が読み上げる。

### 3. 投稿（承認後のみ）
「承認、投稿してください」と言ったら #all_project_activity に投稿する。
承認なしには絶対に投稿しない。

### 手動実行（いつでも）
「今週のアップデート作って」と Claude Code に話しかけるだけで
Notion・Gmail からデータ収集 → 下書き提示 → 承認後に投稿 の全フローが動く。

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

リポジトリの **Settings → Secrets and variables → Actions** に登録する。

| Secret名 | 説明 | 取得場所 |
|----------|------|--------|
| `ANTHROPIC_API_KEY` | Claude API Key | console.anthropic.com |
| `NOTION_API_KEY` | Notion Integration Token | notion.so/my-integrations |
| `NOTION_PROJECTS_DB_ID` | 案件進捗データベースのID | NotionのURL末尾32文字 |
| `NOTION_MEETING_NOTES_DB_ID` | 議事録データベースのID | NotionのURL末尾32文字 |
| `GMAIL_TOKEN_JSON` | Gmail OAuth2トークン | `python scripts/setup_gmail_auth.py` で生成 |
| `SLACK_BOT_TOKEN` | Slack Bot Token | api.slack.com/apps → Bot Token (`xoxb-...`) |
| `SLACK_TEAM_ID` | Slack ワークスペース ID | Slack管理画面 → `T` から始まるID |
| `SLACK_CHANNEL_ID` | 投稿先チャンネルID（#all_project_activity） | チャンネル右クリック → チャンネル詳細 |
| `SLACK_NOTIFY_USER_ID` | 承認依頼DM送付先のユーザーID | Slackプロフィール → メンバーIDをコピー |

## Slack Bot に必要な権限（OAuth Scopes）

Bot Token Scopes として以下を追加する：
- `chat:write` — メッセージ送信
- `channels:read` — チャンネル一覧
- `im:write` — DM 送信
- `groups:read` — プライベートチャンネル読み取り

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
