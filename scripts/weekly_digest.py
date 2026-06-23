#!/usr/bin/env python3
"""
F2 週次ダイジェスト（設計書 4. F2）。
毎週月曜朝に実行。Notion 案件DBの全案件から「今週動いた／止まっている／
期限が近い」を集計・要約し、Slack #all_project_activity に投稿する。
読み取りのみ（Notion へは書き込まない）。
"""

import logging
import os

import anthropic

from common import (
    build_notion,
    days_since,
    fetch_notion_cases,
    post_to_slack,
    today_jst,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# 「今週動いた」と見なす最終更新日のしきい値（日）
ACTIVE_WINDOW_DAYS = 7
CLAUDE_MODEL = "claude-opus-4-8"


def build_summary(cases: list[dict], today: str) -> str:
    """Claude で週報本文（mrkdwn）を生成する。"""
    moved, stalled = [], []
    for c in cases:
        d = days_since(c["最終更新日"])
        bucket = moved if (d is not None and d <= ACTIVE_WINDOW_DAYS) else stalled
        bucket.append(c)

    def fmt(items: list[dict]) -> str:
        return "\n\n".join(
            f"・<{c['url']}|{c['企業名']}／{c['案件名']}>"
            f"（優先度: {c['優先度'] or '未設定'}／最終更新: {c['最終更新日'] or '不明'}）\n"
            f"  現状: {c['現状'][-200:] or '(記載なし)'}\n"
            f"  次アクション: {c['次アクション'] or '(記載なし)'}"
            for c in items
        )

    prompt = f"""あなたは株式会社温泉資源庁（Le Furo）の営業進捗管理アシスタントです。
以下の案件情報をもとに、社内向けの「週次ダイジェスト」を Slack 投稿用の mrkdwn で作成してください。

今日の日付: {today}

## 今週動いた案件（最終更新が直近{ACTIVE_WINDOW_DAYS}日以内）
{fmt(moved) or "(なし)"}

## 止まっている案件（最終更新が{ACTIVE_WINDOW_DAYS}日より前 または 不明）
{fmt(stalled) or "(なし)"}

## 作成ルール
- Slack の mrkdwn 記法（*太字* など。見出しは行頭に *見出し* ）。
- 構成は「① 今週動いた案件」「② 止まっている・要フォロー案件」「③ 期限が近い／次アクションが必要な案件」の3節。
- 各案件は1〜2行で簡潔に。案件名にはリンク（<URL|企業名／案件名> 形式）を付ける。
- 事実は現状の記載に基づく。推測を述べる場合は「（AI整理）」と明示する。
- 冒頭に「:memo: *週次ダイジェスト {today}*」を付ける。全体で長くなりすぎないよう要点に絞る。

mrkdwn の本文のみを返してください（説明やコードフェンスは不要）。"""

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    logger.info("Claude API を呼び出し中（動いた %d 件／止まっている %d 件）", len(moved), len(stalled))
    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    return text


def main():
    today = today_jst()
    logger.info("=== F2 週次ダイジェスト 開始 %s ===", today)

    webhook = os.environ.get("SLACK_WEBHOOK_DIGEST", "")
    if not webhook:
        raise ValueError("環境変数 SLACK_WEBHOOK_DIGEST（#all_project_activity 用）が未設定です")

    notion = build_notion()
    cases = fetch_notion_cases(notion)
    if not cases:
        logger.info("案件なし。終了。")
        return

    summary = build_summary(cases, today)
    post_to_slack(webhook, summary)
    logger.info("=== F2 完了 ===")


if __name__ == "__main__":
    main()
