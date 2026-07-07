# 温泉資源庁 営業自動化ワークフロー

Notion・Gmail・Slack を連携させた営業支援の自動化スクリプト集。
GitHub Actions で定期実行される。

## ワークフロー一覧

### 1. 毎週金曜日 Notion 案件進捗更新（`weekly-notion-update.yml`）
過去7日間の Gmail を読み取り、Notion「🛑 案件進捗（プロパー案件）」DB の
各案件の「現状」を追記更新する。毎週金曜 10:00 JST。

### 2. 毎週金曜日 人脈マップ同期＆協業提案レポート（`weekly-contact-pipeline.yml`）
毎週金曜 10:30 JST に2ステップ実行:

1. **Slack人脈メモ → コンタクトDB 同期**（`scripts/sync_contacts_from_slack.py`）
   - Slack の人脈メモチャンネルの過去7日間の投稿を読み取り、
     Notion「👥 コンタクト（人脈マップ）」DB に人物を自動登録・追記する。
   - 三田・新井・小村の各氏は「昨日◯◯社の△△さんと会った。□□に興味あり」と
     チャンネルに書くだけでよい。
2. **人脈マップ＆協業提案レポート生成**（`scripts/weekly_collab_report.py`）
   - コンタクトDB × 案件進捗DB を突合し、事業群別マッピング・協業提案・
     フォロー漏れアラートをまとめた「【定例資料】人脈マップ＆協業提案」ページを
     Notion に生成し、Slack へ投稿する。

## 必要な GitHub Secrets

| Secret | 用途 |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API（分析・レポート生成） |
| `NOTION_TOKEN` | Notion インテグレーショントークン |
| `NOTION_DATABASE_ID` | 案件進捗DB の ID（省略時デフォルトあり） |
| `GMAIL_TOKEN_JSON` / `GMAIL_CREDENTIALS_JSON` / `GMAIL_USER_EMAIL` | Gmail 読み取り（ワークフロー1） |
| `SLACK_BOT_TOKEN` | Slack Bot トークン（`channels:history` `users:read` `chat:write` スコープ） |
| `SLACK_CONTACT_CHANNEL_ID` | 人脈メモ投稿チャンネルの ID（例: `C0XXXXXXX`） |
| `SLACK_REPORT_CHANNEL_ID` | レポート投稿先チャンネルの ID |

## Notion 側の前提

- 「👥 コンタクト（人脈マップ）」DB（`cb82f51a87b547debf1583e7b0dc1c24`）が
  「営業・案件管理」ページ配下に存在すること（作成済み）。
- 案件進捗DBとの双方向リレーション「関連案件」⇔「コンタクト」設定済み。
- Notion インテグレーションが両DBと「営業・案件管理」ページに接続されていること。

## セットアップ手順（人脈パイプライン）

1. Slack に `#人脈メモ` チャンネルを作成し、Bot を招待する。
2. 上記 Secrets（`SLACK_BOT_TOKEN` / `SLACK_CONTACT_CHANNEL_ID` / `SLACK_REPORT_CHANNEL_ID`）を
   リポジトリの Settings → Secrets and variables → Actions に登録する。
3. Actions タブから `毎週金曜日 人脈マップ同期＆協業提案レポート` を手動実行して動作確認する。
