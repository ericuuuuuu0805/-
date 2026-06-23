-- 温泉資源庁 / Le Furo - 初期スキーマ
-- DB: lod-be_claude (MySQL 8.0)
-- 適用方法は deploy/README または lefuro-web/README.md を参照。
--
-- 注意: DROP / 既存データを壊す変更は必ず人に確認すること。
--       本ファイルは CREATE TABLE IF NOT EXISTS のみで安全側に倒している。

SET NAMES utf8mb4;

-- お問い合わせ / 申込みなどの汎用エントリ例
CREATE TABLE IF NOT EXISTS contacts (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  name        VARCHAR(100)  NOT NULL,
  email       VARCHAR(255)  NOT NULL,
  message     TEXT          NOT NULL,
  created_at  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_contacts_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 動作確認用サンプル（資料 6-1 と同等）
CREATE TABLE IF NOT EXISTS sample (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  name        VARCHAR(100),
  created_at  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
