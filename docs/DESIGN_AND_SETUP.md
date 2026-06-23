# 設計書：Eric営業秘書（温泉資源庁）— GitHub Actions 版 構築・展開ガイド v1.0

別の環境でも同じ仕組みを再現できるようにまとめた、本リポジトリの設計＆セットアップ手順書。
本書だけで「何が・どう動き・どの順で設定すれば再現できるか」が分かることを目標とする。

- 対象：温泉資源庁（Le Furo）の営業案件管理を、**GitHub Actions + Python + Claude API** で半自動化する仕組み
- 設計書（Google ドキュメント版 v0.2）の **F1〜F4** を、本リポジトリにコード実装したもの。**出力先は Notion と Slack**（設計書の Drive/Gmail は使わない）。
- 方針：**読み書き分離（書くのはF1とF4の新規ページのみ）・追記専用・迷ったら止める・曜日分散**
- 関連ファイル：
  - F1 案件同期：`scripts/update_notion_from_gmail.py` ＋ `.github/workflows/weekly-notion-update.yml`
  - F2 週次ダイジェスト：`scripts/weekly_digest.py` ＋ `.github/workflows/weekly-digest.yml`
  - F3 休眠アラート：`scripts/dormant_alert.py` ＋ `.github/workflows/dormant-alert.yml`
  - F4 定例会資料：`scripts/meeting_doc.py` ＋ `.github/workflows/meeting-doc.yml`
  - 共通：`scripts/common.py`（Notion取得・Slack投稿・日付）／`scripts/setup_gmail_token.py`／`requirements.txt`

| 機能 | 役割 | 起動 | 出力先 | 書込 |
| --- | --- | --- | --- | --- |
| F1 案件同期 | 直近7日のGmailを現状に追記 | 金 10:00 JST | Notion（現状・最終更新日） | ○（追記） |
| F2 週次ダイジェスト | 今週の動き/停滞/期限を要約 | 月 09:00 JST | Slack #all_project_activity | × |
| F3 休眠アラート | 30日動きのない案件を抽出 | 水 10:00 JST | Slack #sales | × |
| F4 定例会資料 | High案件を現状/論点/次アクションに整形 | 定例前日朝（既定 木 08:00 JST・要調整） | Notion 新規ページ | ○（新規のみ） |

---

## 1. 目的とスコープ
- Eric が手を動かさずに、メールの動きを案件DBの「現状」に反映できる状態をつくる。
- 正は Notion の案件DB。Gmail の直近の動きを Claude が要約し、各案件の「現状」に**追記**する。
- やることは1つだけ：**Gmail（直近7日）→ Claude 分析 → Notion 現状の追記 ＋ 最終更新日の更新**。

| 項目 | 内容 |
| --- | --- |
| 起動 | 毎週金曜 10:00 JST（cron）＋ 手動実行（workflow_dispatch） |
| 入力 | 過去7日間の Gmail（接続アカウントの受信箱全体） |
| 出力 | Notion 案件DB：`現状`（追記）／`最終更新日`（当日） |
| 書込 | **あり**（追記専用・正式項目は触らない） |
| 実行基盤 | GitHub Actions（ubuntu-latest / Python 3.11 / timeout 30分） |

## 2. システム全体像
```
GitHub Actions（毎週金 or 手動）
  └─ scripts/update_notion_from_gmail.py
       ├─ Gmail API   … 直近7日のメールを取得（readonly）
       ├─ Notion API  … 案件一覧を取得
       ├─ Claude API  … メール×案件を突合し「現状への追記文」をJSONで生成
       └─ Notion API  … 各案件の「現状」を追記更新＋「最終更新日」を当日に
```
- 状態（しおり）は持たない。**毎回「過去7日のメール × 全案件」を見て、追記すべき新情報だけ**を反映する設計。
- 二重追記の防止は「既存の現状を Claude に見せ、記録済みの内容は出力しない」ルールで担保（厳密な冪等性はモデル判断に依存）。

## 3. 前提条件（必要なもの）
- **GitHub リポジトリ**（Actions 有効）。
- **API / 接続**
  - Anthropic（Claude API）キー：`ANTHROPIC_API_KEY`
  - Gmail（OAuth2・**gmail.readonly**）：`GMAIL_TOKEN_JSON`（実行時に使用）
  - Notion インテグレーション トークン：`NOTION_TOKEN`（案件DBに read/write を共有）
  - Notion 案件DBのデータベースID：`NOTION_DATABASE_ID`
- **依存**（`requirements.txt`）
  - `anthropic>=0.30.0` / `notion-client>=2.2.1` / `google-auth>=2.29.0` / `google-auth-oauthlib>=1.2.0` / `google-api-python-client>=2.125.0`

## 4. GitHub Secrets（必須・差し替え対象）
ワークフローが参照する環境変数。リポジトリの Settings → Secrets and variables → Actions に登録する。

| Secret | 用途 | 備考 |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | Claude API 認証 | 必須 |
| `GMAIL_TOKEN_JSON` | Gmail 読み取り用 OAuth トークン | **実行時に実際に使われる**。§6で取得 |
| `NOTION_TOKEN` | Notion API 認証 | インテグレーションを案件DBに招待しておく |
| `NOTION_DATABASE_ID` | 対象の案件DB | 未設定時はコード内デフォルトを使用（§8） |
| `GMAIL_CREDENTIALS_JSON` | OAuth クライアント情報 | ワークフローに渡しているが、実行スクリプトは未使用（トークン取得時のみ必要） |
| `GMAIL_USER_EMAIL` | 対象メールアドレス | 同上：現状スクリプトは `userId="me"` を使い未参照。将来の明示指定用に予約 |
| `SLACK_WEBHOOK_DIGEST` | F2 の投稿先 #all_project_activity | Eric 発行の Incoming Webhook URL |
| `SLACK_WEBHOOK_ALERT` | F3 の投稿先 #sales | 同上（チャンネルごとに別 URL） |
| `NOTION_MEETING_PARENT_PAGE_ID` | F4 定例資料ページを作成する親ページID | インテグレーションが書込権限を持つページ |

> Slack は**チャンネルごとに Incoming Webhook URL が分かれる**ため、F2 と F3 で別々の Secret を使う。
> Webhook は Slack App の「Incoming Webhooks」を有効化し、対象チャンネルを選んで発行する。

> メモ：`GMAIL_CREDENTIALS_JSON` / `GMAIL_USER_EMAIL` は現行コードでは読み取られない。
> 登録は任意だが、ワークフロー定義に env として残っているため空でも設定しておくと警告を避けられる。

## 5. データ設計（Notion 案件DB）
- 正の案件DB ＝ 「案件進捗（プロパー案件）」。`NOTION_DATABASE_ID` で指す。
- スクリプトが読む列：`案件名` / `企業名` / `カテゴリー`(multi) / `優先度`(select) / `現状` / `次アクション`。
- スクリプトが書く列（**ここだけ**）：
  - `現状`（rich_text）… 既存文 ＋ 空行 ＋ 追記。**既存は保持、追記のみ末尾に足す**。
  - `最終更新日`（date）… 実行日（JST）。
- それ以外の正式項目（ステージ／契約／請求 等）は**一切触らない**。

## 6. Gmail トークンの取得（初回・手元で1回だけ）
`scripts/setup_gmail_token.py` を使う。
1. Google Cloud Console で Gmail API を有効化し、OAuth2 クライアントID（**デスクトップアプリ**）を作成。
2. `credentials.json` をスクリプトと同じディレクトリに置く。
3. `python scripts/setup_gmail_token.py` を実行 → ブラウザで認可 → `token.json` 生成。
4. `token.json` の中身を GitHub Secret `GMAIL_TOKEN_JSON` に登録。
5. （任意）`credentials.json` の中身を `GMAIL_CREDENTIALS_JSON` に登録。
- スコープは `gmail.readonly`（読み取りのみ。送信・変更はしない）。

## 7. 処理フロー（スクリプト内部の詳細）
`scripts/update_notion_from_gmail.py` の流れ：
1. **今日（JST）を確定** → ログ開始。
2. **Gmail 取得** `fetch_recent_emails(days=7)`：`after:YYYY/MM/DD` で検索、200件/ページでページング、本文は text/plain を優先抽出し**3000字に切り詰め**。0件なら終了。
3. **Notion 取得** `fetch_notion_cases()`：`databases.query` を100件/ページでページング、全案件の対象列を抽出。
4. **Claude 分析** `analyze_with_claude()`：
   - 案件側は `現状` の**直近200字**だけを提示（既記録の判定材料）。メール側は本文1500字。
   - モデル `claude-opus-4-8` / `max_tokens=4096`。出力は **JSON 配列のみ**（```フェンスは除去）。
   - 各要素：`{ "page_id", "現状_追記", "関連メール件名" }`。**関連メールのない案件・既記録のみの案件は出力しない**。
5. **Notion 更新** `apply_updates()`：
   - ページIDはハイフン有無の両対応でマッピング。
   - **書込直前に `pages.retrieve` で最新の現状を再取得**（手動編集との競合回避）。
   - `現状` = 既存 ＋ `\n\n` ＋ 追記。rich_text は**1999字ごとに分割**して格納（Notion 1ブロック上限対策）。
   - `最終更新日` = 当日。
6. 更新件数をログに出して終了。

## 7-2. F2〜F4 の処理フロー
共通基盤は `scripts/common.py`（Notion 全案件取得・Slack Incoming Webhook 投稿・JST 日付）。
案件DBのフィールド対応：設計書の「最終アクティビティ日」＝本DBの **`最終更新日`**、「活動ログ」＝ **`現状`**、「優先度=高」＝ **`High Priority`**。

- **F2 週次ダイジェスト**（`weekly_digest.py`・読み取りのみ）
  1. 全案件を取得し、`最終更新日` が直近7日以内かで「動いた／止まっている」に振り分け。
  2. Claude（`claude-opus-4-8`）で mrkdwn の週報本文を生成（①動いた②停滞③期限/次アクション の3節、案件名はリンク付き、推測は「（AI整理）」明示）。
  3. `SLACK_WEBHOOK_DIGEST` で #all_project_activity に投稿。
- **F3 休眠アラート**（`dormant_alert.py`・ルールベース・Claude不使用）
  1. 全案件を取得。`現状` に終了系キーワード（失注/入金済/完了/クローズ/終了/見送り/中止）を含む案件は除外。
  2. `本日 − 最終更新日 > 30日` を「休眠中」、`最終更新日` 未入力を「要確認」に分類（経過日数で降順）。
  3. 対象が無ければ投稿しない。あれば `SLACK_WEBHOOK_ALERT` で #sales に投稿。
- **F4 定例会資料**（`meeting_doc.py`・Notion 新規ページのみ書込）
  1. `優先度 = High Priority` の案件を抽出。
  2. Claude で各案件を「現状（事実）／論点（AI整理）／次アクション」に整形（JSON）。
  3. `NOTION_MEETING_PARENT_PAGE_ID` 配下に「【定例資料】High Priority案件 YYYY-MM-DD」を新規作成（100ブロック超は追記）。案件DBには書き込まない。

## 8. 環境固有値（自環境の値に差し替える）
| 項目 | 本番(温泉資源庁)の値 | 差し替え方法 |
| --- | --- | --- |
| Notion 案件DB | `c030de8d863640358e70b42f61de1318`（コード内デフォルト） | Secret `NOTION_DATABASE_ID` で上書き推奨 |
| 起動スケジュール | `cron: 0 1 * * 5`（金10:00 JST） | ワークフローの cron を編集 |
| 対象メール | 接続アカウントの受信箱（`userId="me"`） | トークンを差し替え |
| Claude モデル | `claude-opus-4-8` | スクリプト内 `model=` を編集 |
| 取得期間 | 7日 | `fetch_recent_emails(days=...)` を編集 |

## 9. 安全原則（事故防止）
- **追記専用**：`現状` の既存内容は絶対に消去・変更しない（プロンプト＋結合ロジックの二重で担保）。
- **書込直前再取得**：手動編集との競合を避けるため、更新の直前に最新の現状を取り直す。
- **正式項目は不可侵**：書くのは `現状` と `最終更新日` のみ。
- **読み取りは最小権限**：Gmail は readonly。送信・ラベル変更はしない。
- **関連のない案件は触らない**：Claude が紐付かないと判断した案件は更新対象に含めない。

## 10. 新環境セットアップ手順（順番厳守）
1. このリポジトリ（または同等の3ファイル：workflow / 2スクリプト / requirements）を用意。
2. Notion インテグレーションを作成し、**案件DBに招待**。`NOTION_TOKEN` と `NOTION_DATABASE_ID` を控える。
3. §6 で Gmail の `token.json` を取得。
4. GitHub Secrets（§4）を登録：`ANTHROPIC_API_KEY` / `GMAIL_TOKEN_JSON` / `NOTION_TOKEN` / `NOTION_DATABASE_ID`（＋任意の2つ）。
5. Actions タブ →「毎週金曜日 Notion 案件進捗更新」を **workflow_dispatch で手動実行**してテスト。
6. ログで「取得メール数 / 案件数 / Claude が N 件提案 / 更新完了」を確認。Notion 側の現状が**追記**になっているか（上書きされていないか）を目視確認。
7. 問題なければスケジュール実行（金 10:00 JST）に任せる。

## 11. 既知の制約・ハマりどころ
- **冪等性はモデル判断依存**：「既記録は出力しない」ルールで二重追記を抑えるが、表現が変わると重複追記の可能性。重要案件は最初のうち目視確認を。
- **現状の提示は直近200字のみ**：古い記録は Claude に見えないため、長期間前と同内容の再追記が起こり得る。
- **Gmail は受信箱全体が対象**：`after:` のみで絞っているため、ノイズメールも入力に含まれる（Claude 側で案件紐付け判定）。
- **`GMAIL_CREDENTIALS_JSON` / `GMAIL_USER_EMAIL` は現行未使用**：ワークフローに env として残るだけ。明示利用したい場合はスクリプト改修が必要。
- **トークン失効**：`GMAIL_TOKEN_JSON` の refresh_token が無効化されると失敗する。失効時は §6 を再実行。
- **状態を持たない**：しおり（処理済みID等）は保存していない。実行のたびに直近7日を再評価する。

## 12. 改善余地（任意）
- 処理済みメールID / 追記済みハッシュを保存して**厳密な冪等性**を持たせる（リポジトリにコミット or 外部ストア）。
- 現状の全文を（要約して）Claude に渡し、再追記の取りこぼし/重複を減らす。
- 失敗時の通知（Slack/メール）と、`GMAIL_USER_EMAIL` による対象アカウントの明示化。

---
本書と3ファイル（workflow / 2スクリプト / requirements）をコピーし、§10 の手順を辿れば、別環境でも同じ自動更新を立ち上げられる。
