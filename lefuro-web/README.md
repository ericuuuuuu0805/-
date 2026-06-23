# 温泉資源庁 / Le Furo — Web 開発プロジェクト

`www2.le-furo.com`（さくらインターネット）上で動かす、オリジナル Web ページ・アプリの
開発リポジトリ雛形です。静的ページ + PHP + MySQL 構成。

## ディレクトリ構成

```
lefuro-web/
├── public/                 公開フォルダ（= サーバの ~/www/www2 に対応）
│   ├── index.html          トップページ
│   ├── assets/
│   │   ├── style.css
│   │   └── app.js
│   ├── api/
│   │   ├── db.php          MySQL 接続ヘルパー（config.php を読む）
│   │   └── health.php      PHP/DB ヘルスチェック（JSON）
│   ├── config.sample.php   設定テンプレート → config.php に複製して使う
│   └── .htaccess.sample    Basic 認証テンプレート → .htaccess に複製
├── db/
│   └── schema.sql          初期テーブル定義（IF NOT EXISTS のみ）
├── deploy/
│   ├── .env.sample         デプロイ認証情報テンプレート → .env に複製
│   └── deploy.sh           public/ を FTP でアップロード
├── .gitignore              秘密ファイルを除外
└── README.md
```

## 秘密情報の扱い（重要）

- **パスワードはコミットしない。** 実値は `config.php` / `deploy/.env`（どちらも `.gitignore` 済み）に置く。
- さくらの会員 / サーバ / DB 各パスワードの**正本は Google Drive**
  「05_各種ツール/さくらインターネット/取り扱い注意-アクセス情報」Doc。
- 漏洩時はさくらコントロールパネルで各パスワードを変更する。

## ⚠️ ネットワークについての前提

このリポジトリで**コードを書くのはネット不要**だが、**配置（デプロイ）には外向き通信が要る**。

- **Claude Code on the web のクラウド環境**は egress 許可リスト制。
  - HTTP/HTTPS で `www2.le-furo.com` を**許可リストに追加**すれば、Web 閲覧・ヘルスチェックは可能。
    設定: https://code.claude.com/docs/en/claude-code-on-the-web
  - **FTP(21)/SSH(22) は基本的に通らない**（プロキシは HTTP/HTTPS のみ中継）。
    → `deploy.sh` や SSH トンネルは、**FTP が通る環境（手元 PC 等）で実行**する。

## セットアップ手順

### 1. 設定ファイルを用意（ローカル、コミットしない）
```sh
cp public/config.sample.php public/config.php   # DBパスワードを記入
cp deploy/.env.sample        deploy/.env          # FTPパスワードを記入
```

### 2. デプロイ（FTP が通る環境で）
```sh
./deploy/deploy.sh                  # public/ 全体を ~/www/www2 へ
./deploy/deploy.sh public/index.html  # 単一ファイルだけ
```

### 3. 動作確認
```sh
# トップページ（SSL 未設定のうちは http、DNSキャッシュ回避に --resolve）
curl -sS -o /dev/null -w "%{http_code}\n" \
  --resolve www2.le-furo.com:80:219.94.155.251 http://www2.le-furo.com/

# ヘルスチェック（PHP/DB 接続を JSON で確認）
curl -sS --resolve www2.le-furo.com:80:219.94.155.251 \
  http://www2.le-furo.com/api/health.php
```

### 4. DB テーブル作成
外部から MySQL 直結(3306)は不可。次のいずれか:
- **phpMyAdmin**（さくらコントロールパネル）に `db/schema.sql` を貼って実行（推奨・GUI）
- **SSH トンネル**（FTP/SSH が通る環境）:
  ```sh
  ssh -N -L 13306:mysql3110.db.sakura.ne.jp:3306 lod-be@lod-be.sakura.ne.jp &
  mysql -h 127.0.0.1 -P 13306 -u lod-be_claude -p lod-be_claude < db/schema.sql
  ```

### 5. テスト公開を Basic 認証で保護
```sh
cp public/.htaccess.sample public/.htaccess     # AuthUserFile の絶対パスを確認
htpasswd -nbB admin 'パスワード' > public/.htpasswd
./deploy/deploy.sh public/.htaccess public/.htpasswd
```

## 破壊的操作のルール

DB の `INSERT/UPDATE/DELETE/DROP`、サーバ上のファイル**削除・上書き**は、
**実行前に必ず人へ確認**する（正本ドキュメントの運用ルール）。

## SSL（HTTPS）について

現状 `www2.le-furo.com` 専用証明書は未発行。
さくらコントロールパネル →「ドメイン/SSL」→ 無料SSL(Let's Encrypt) を有効化して発行する。
発行後は `deploy/.env` の `SITE_SCHEME=https` に切り替える。
