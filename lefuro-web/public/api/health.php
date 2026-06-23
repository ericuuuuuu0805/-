<?php
/**
 * health.php — サーバ／DB ヘルスチェック用エンドポイント
 *
 * PHP の稼働確認と MySQL への接続確認を JSON で返す。
 * config.php が無い／DB 未接続でも 200 を返し、状態を JSON で示す。
 */

declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

$result = [
    'ok'          => true,
    'time'        => date('c'),
    'php_version' => PHP_VERSION,
    'https'       => (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off'),
    'db'          => ['connected' => false],
];

try {
    require __DIR__ . '/db.php';
    $db = lefuro_db();
    $res = $db->query('SELECT VERSION() AS v');
    $row = $res ? $res->fetch_assoc() : null;
    $result['db'] = [
        'connected'     => true,
        'server_version' => $row['v'] ?? null,
    ];
    $db->close();
} catch (Throwable $e) {
    $result['db'] = [
        'connected' => false,
        'error'     => $e->getMessage(),
    ];
}

echo json_encode($result, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE);
