<?php
/**
 * config.sample.php — 設定テンプレート
 *
 * 使い方:
 *   1. このファイルを config.php としてコピー
 *   2. 実際の DB 認証情報を記入
 *   3. config.php は Git にコミットしない（.gitignore 済み）
 *   4. サーバへは config.php を FTP で ~/www/www2/ に配置
 *
 * ※ 平文パスワードを含むため、公開フォルダ直下でも .ht* で保護するか、
 *    可能なら getenv() でサーバ環境変数から読む運用が望ましい。
 */

return [
    'db' => [
        'host'    => getenv('LEFURO_DB_HOST') ?: 'mysql3110.db.sakura.ne.jp',
        'name'    => getenv('LEFURO_DB_NAME') ?: 'lod-be_claude',
        'user'    => getenv('LEFURO_DB_USER') ?: 'lod-be_claude',
        'pass'    => getenv('LEFURO_DB_PASS') ?: 'ここにDBパスワードを記入',
        'charset' => 'utf8mb4',
    ],
];
