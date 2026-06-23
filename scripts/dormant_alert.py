#!/usr/bin/env python3
"""
F3 休眠アラート（設計書 4. F3）。
毎週水曜に実行。Notion 案件DBの「最終更新日（＝最終アクティビティ日）」を見て、
本日 − 最終活動 > 30日 かつ 終了系でない案件を抽出し、Slack #sales へ投稿する。
読み取りのみ・ルールベース（Claude は使わない）。
"""

import logging
import os

from common import (
    build_notion,
    days_since,
    fetch_notion_cases,
    post_to_slack,
    today_jst,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DORMANT_DAYS = 30
# 「終了系」と判定する現状テキストのキーワード（誤検知を避け保守的に）
CLOSED_KEYWORDS = ("失注", "入金済", "完了", "クローズ", "終了", "見送り", "中止")


def is_closed(case: dict) -> bool:
    text = case.get("現状", "")
    return any(k in text for k in CLOSED_KEYWORDS)


def build_message(cases: list[dict], today: str) -> str | None:
    dormant: list[tuple[int, dict]] = []
    unknown: list[dict] = []

    for c in cases:
        if is_closed(c):
            continue
        d = days_since(c["最終更新日"])
        if d is None:
            unknown.append(c)
        elif d > DORMANT_DAYS:
            dormant.append((d, c))

    if not dormant and not unknown:
        return None

    dormant.sort(key=lambda x: x[0], reverse=True)

    lines = [f":alarm_clock: *休眠アラート {today}*（{DORMANT_DAYS}日以上動きのない案件）", ""]

    if dormant:
        lines.append(f"*■ 休眠中（{len(dormant)}件）*")
        for d, c in dormant:
            lines.append(
                f"・<{c['url']}|{c['企業名']}／{c['案件名']}>"
                f"（{d}日経過／優先度: {c['優先度'] or '未設定'}）"
            )
        lines.append("")

    if unknown:
        lines.append(f"*■ 要確認：最終更新日が未入力（{len(unknown)}件）*")
        for c in unknown:
            lines.append(f"・<{c['url']}|{c['企業名']}／{c['案件名']}>")
        lines.append("")

    lines.append("_終了系（失注・入金済・完了 等）は現状の記載から自動除外しています。_")
    return "\n".join(lines)


def main():
    today = today_jst()
    logger.info("=== F3 休眠アラート 開始 %s ===", today)

    webhook = os.environ.get("SLACK_WEBHOOK_ALERT", "")
    if not webhook:
        raise ValueError("環境変数 SLACK_WEBHOOK_ALERT（#sales 用）が未設定です")

    notion = build_notion()
    cases = fetch_notion_cases(notion)

    message = build_message(cases, today)
    if message is None:
        logger.info("休眠・要確認の案件なし。投稿せず終了。")
        return

    post_to_slack(webhook, message)
    logger.info("=== F3 完了 ===")


if __name__ == "__main__":
    main()
