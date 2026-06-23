#!/usr/bin/env python3
"""
F4 定例会資料（設計書 4. F4）。
定例の前日/当日朝に実行。優先度=High Priority の案件について
「現状・論点・次アクション」を整形し、Notion に新規ページとして作成する。
（設計書では Drive docx だが、本実装では出力先を Notion に変更）
案件DBは読み取りのみ。書き込むのは新規の定例資料ページだけ。
"""

import json
import logging
import os

import anthropic

from common import build_notion, fetch_notion_cases, today_jst

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

HIGH_PRIORITY = "High Priority"
CLAUDE_MODEL = "claude-opus-4-8"


def format_cases(cases: list[dict], today: str) -> list[dict]:
    """各案件を {案件名, 企業名, 現状, 論点, 次アクション} に整形（Claude）。"""
    cases_text = "\n\n---\n\n".join(
        f"【案件ID】{c['id']}\n【企業名】{c['企業名']}\n【案件名】{c['案件名']}\n"
        f"【カテゴリー】{', '.join(c['カテゴリー'])}\n【最終更新日】{c['最終更新日'] or '不明'}\n"
        f"【現状】{c['現状'] or '(記載なし)'}\n【次アクション】{c['次アクション'] or '(記載なし)'}"
        for c in cases
    )

    prompt = f"""あなたは株式会社温泉資源庁（Le Furo）の営業会議の準備担当です。
以下の High Priority 案件について、定例会議用の資料を作成してください。

今日の日付: {today}

## 対象案件
{cases_text}

## ルール
- 各案件を「現状（事実）／論点（AI整理）／次アクション」に整形する。
- 「現状」は記載されている事実のみ。創作しない。
- 「論点」は会議で詰めるべき点。AIによる整理である旨が分かる書き方にする。
- 「次アクション」は具体的に。不明な場合は「要確認」と書く。

## 出力形式（JSON 配列のみ）
[
  {{
    "案件名": "企業名／案件名",
    "現状": "...",
    "論点": "...",
    "次アクション": "..."
  }}
]

JSON のみ返答してください。説明やコードフェンスは不要です。"""

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    logger.info("Claude API を呼び出し中（%d 件）", len(cases))
    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    return json.loads(raw)


def _heading(text: str, level: int = 2) -> dict:
    key = f"heading_{level}"
    return {
        "object": "block",
        "type": key,
        key: {"rich_text": [{"type": "text", "text": {"content": text[:2000]}}]},
    }


def _para(text: str) -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": text[:2000]}}]},
    }


def build_blocks(formatted: list[dict], today: str) -> list[dict]:
    blocks: list[dict] = [
        _para(f"対象: 優先度 = High Priority（{len(formatted)}件）／生成日: {today}"),
        _para("※ 論点はAIによる整理です。会議前に内容をご確認ください。"),
    ]
    for c in formatted:
        blocks.append(_heading(c.get("案件名", "(案件名不明)"), level=2))
        blocks.append(_para(f"【現状】{c.get('現状', '(記載なし)')}"))
        blocks.append(_para(f"【論点（AI整理）】{c.get('論点', '(なし)')}"))
        blocks.append(_para(f"【次アクション】{c.get('次アクション', '要確認')}"))
    return blocks


def main():
    today = today_jst()
    logger.info("=== F4 定例会資料 開始 %s ===", today)

    parent_id = os.environ.get("NOTION_MEETING_PARENT_PAGE_ID", "")
    if not parent_id:
        raise ValueError(
            "環境変数 NOTION_MEETING_PARENT_PAGE_ID（資料を作成する親ページID）が未設定です"
        )

    notion = build_notion()
    cases = [c for c in fetch_notion_cases(notion) if c["優先度"] == HIGH_PRIORITY]
    if not cases:
        logger.info("High Priority 案件なし。終了。")
        return

    formatted = format_cases(cases, today)
    blocks = build_blocks(formatted, today)

    title = f"【定例資料】High Priority案件 {today}"
    page = notion.pages.create(
        parent={"page_id": parent_id},
        properties={"title": [{"type": "text", "text": {"content": title}}]},
        children=blocks[:100],  # Notion は1リクエスト100ブロックまで
    )

    # 100ブロックを超える分は追記
    for i in range(100, len(blocks), 100):
        notion.blocks.children.append(block_id=page["id"], children=blocks[i : i + 100])

    logger.info("=== F4 完了: %s（%s） ===", title, page.get("url", ""))


if __name__ == "__main__":
    main()
