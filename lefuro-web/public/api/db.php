<?php
/**
 * db.php — MySQL 接続ヘルパー（mysqli）
 *
 * config.php（gitignore 済み）から認証情報を読み込み、
 * mysqli 接続を返す。例外時はエラーを投げる。
 */

declare(strict_types=1);

function lefuro_config(): array
{
    $path = __DIR__ . '/../config.php';
    if (!is_file($path)) {
        throw new RuntimeException('config.php が見つかりません。config.sample.php を複製してください。');
    }
    return require $path;
}

function lefuro_db(): mysqli
{
    $cfg = lefuro_config()['db'];

    mysqli_report(MYSQLI_REPORT_ERROR | MYSQLI_REPORT_STRICT);

    $db = new mysqli($cfg['host'], $cfg['user'], $cfg['pass'], $cfg['name']);
    $db->set_charset($cfg['charset']);

    return $db;
}
