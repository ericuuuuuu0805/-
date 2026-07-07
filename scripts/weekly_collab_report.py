#!/usr/bin/env python3
"""
コンタクトDB × 案件進捗DB を突合し、事業群ごとの人脈マッピングと
協業提案をまとめた週次レポートを Notion に生成、Slack へ投稿するスクリプト。

「初回接触・関係構築中の人物を、既存顧客・導入実績と掛け合わせると
どんな提案ができるか」を毎週自動で洗い出す。
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import anthropic
import requests
from notion_client import Client as NotionClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

DEFAULT_CONTACT_DATABASE_ID = os.environ.get(
    "CONTACT_DATABASE_ID", "cb82f51a87b547debf1583e7b0dc1c24"
)
DEFAULT_CASE_DATABASE_ID = os.environ.get(
    "NOTION_DATABASE_ID", "c030de8d863640358e70b42f61de1318"
)
# レポートの作成先（営業・案件管理ページ）
DEFAULT_REPORT_PARENT_PAGE_ID = os.environ.get(
    "REPORT_PARENT_PAGE_ID", "dfb14159451d44448fbeafd148ebc81a"
)


# ── Notion 取得 ───────────────────────────────────────────────────────────────

def _title(props: dict, key: str) -> str:
    return "".join(r["plain_text"] for r in props.get(key, {}).get("title", []))


def _rich_text(props: dict, key: str) -> str:
    return "".join(r["plain_text"] for r in props.get(key, {}).get("rich_text", []))


def _select(props: dict, key: str) -> str:
    s = props.get(key, {}).get("select") or {}
    return s.get("name", "")


def _multi_select(props: dict, key: str) -> list[str]:
    return [s["name"] for s in props.get(key, {}).get("multi_select", [])]


def _query_all(notion: NotionClient, database_id: str) -> list[dict]:
    pages: list[dict] = []
    cursor = None
    while True:
        kwargs: dict = {"database_id": database_id, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        result = notion.databases.query(**kwargs)
        pages.extend(result["results"])
        if not result.get("has_more"):
            break
        cursor = result.get("next_cursor")
    return pages


def fetch_contacts(notion: NotionClient, database_id: str) -> list[dict]:
    contacts = []
    for page in _query_all(notion, database_id):
        p = page["properties"]
        contacts.append(
            {
                "名前": _title(p, "名前"),
                "会社・組織": _rich_text(p, "会社・組織"),
                "役職・部署": _rich_text(p, "役職・部署"),
                "事業群": _multi_select(p, "事業群"),
                "関係ステータス": _select(p, "関係ステータス"),
                "担当": _multi_select(p, "担当"),
                "接触経緯": _rich_text(p, "接触経緯"),
                "メモ": _rich_text(p, "メモ")[:300],
            }
        )
    logger.info("コンタクト数: %d 件", len(contacts))
    return contacts


def fetch_cases(notion: NotionClient, database_id: str) -> list[dict]:
    cases = []
    for page in _query_all(notion, database_id):
        p = page["properties"]
        cases.append(
            {
                "案件名": _title(p, "案件名"),
                "企業名": _select(p, "企業名"),
                "カテゴリー": _multi_select(p, "カテゴリー"),
                "フェーズ": _select(p, "フェーズ"),
                "現状": _rich_text(p, "現状")[:300],
            }
        )
    logger.info("案件数: %d 件", len(cases))
    return cases


# ── Claude レポート生成 ────────────────────────────────────────────────────────

def generate_report(contacts: list[dict], cases: list[dict], today: str) -> str:
    contacts_text = "\n".join(
        f"- {c['名前']}（{c['会社・組織']} {c['役職・部署']}）"
        f"｜事業群: {', '.join(c['事業群'])}｜ステータス: {c['関係ステータス']}"
        f"｜担当: {', '.join(c['担当'])}｜経緯: {c['接触経緯']}｜メモ: {c['メモ']}"
        for c in contacts
    )
    cases_text = "\n".join(
        f"- {c['企業名']}｜{c['案件名']}｜カテゴリー: {', '.join(c['カテゴリー'])}"
        f"｜フェーズ: {c['フェーズ']}｜現状: {c['現状']}"
        for c in cases
    )

    prompt = f"""あなたは株式会社温泉資源庁（Le Furo）の事業開発アシスタントです。
コンタクトDB（人脈）と案件進捗DBを突合し、週次の「人脈マップ＆協業提案レポート」を
Markdown で作成してください。

今日の日付: {today}

## コンタクトDB
{contacts_text}

## 案件進捗DB
{cases_text}

## レポート構成（この順で・Markdown で出力）
# 人脈マップ＆協業提案（{today}）

## 1. 事業群別マッピングサマリー
事業群ごとに「既存顧客」「商談中・案件化」「初回接触・関係構築中」の人数と主な顔ぶれを簡潔に。

## 2. 今週の協業提案（最大5件）
初回接触〜関係構築中の人物・企業に対して、既存顧客・導入実績・キーパーソンを
掛け合わせた具体的な提案仮説。各件について:
- **対象**: 人物・企業名
- **掛け合わせる実績・人脈**: 該当する既存顧客や事例
- **提案仮説**: 1〜3行
- **ネクストアクション**: 誰が何をするか

## 3. フォロー漏れアラート
初回接触のまま止まっている・最終接触から時間が空いていそうな人物のリスト。

## ルール
- 実データに基づき、推測は「仮説」と明示する。
- 簡潔に。全体で1500字以内目安。
- Markdown のみ返答してください。"""

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    logger.info("Claude API を呼び出し中...")
    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


# ── Notion ページ作成 ─────────────────────────────────────────────────────────

def _md_to_blocks(markdown: str) -> list[dict]:
    """簡易 Markdown → Notion ブロック変換（見出し・箇条書き・段落）。"""

    def rt(text: str) -> list[dict]:
        return [{"type": "text", "text": {"content": text[:1999]}}]

    blocks: list[dict] = []
    for line in markdown.splitlines():
        line = line.rstrip()
        if not line.strip():
            continue
        if line.startswith("### "):
            blocks.append({"heading_3": {"rich_text": rt(line[4:])}})
        elif line.startswith("## "):
            blocks.append({"heading_2": {"rich_text": rt(line[3:])}})
        elif line.startswith("# "):
            blocks.append({"heading_1": {"rich_text": rt(line[2:])}})
        elif line.lstrip().startswith(("- ", "* ")):
            text = line.lstrip()[2:].replace("**", "")
            blocks.append({"bulleted_list_item": {"rich_text": rt(text)}})
        else:
            blocks.append({"paragraph": {"rich_text": rt(line.replace('**', ''))}})
    return blocks[:100]  # Notion API の1リクエスト上限


def create_notion_report(notion: NotionClient, markdown: str, today: str) -> str:
    page = notion.pages.create(
        parent={"page_id": DEFAULT_REPORT_PARENT_PAGE_ID},
        properties={
            "title": [
                {
                    "type": "text",
                    "text": {"content": f"【定例資料】人脈マップ＆協業提案（{today}）"},
                }
            ]
        },
        children=_md_to_blocks(markdown),
    )
    logger.info("Notion レポート作成: %s", page["url"])
    return page["url"]


# ── Slack 投稿 ────────────────────────────────────────────────────────────────

def post_to_slack(markdown: str, notion_url: str, today: str):
    token = os.environ.get("SLACK_BOT_TOKEN")
    channel = os.environ.get("SLACK_REPORT_CHANNEL_ID")
    if not token or not channel:
        logger.info("Slack 投稿はスキップ（SLACK_BOT_TOKEN / SLACK_REPORT_CHANNEL_ID 未設定）")
        return

    summary = markdown
    if len(summary) > 2800:
        summary = summary[:2800] + "\n…（続きは Notion で）"

    resp = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "channel": channel,
            "text": f"📊 人脈マップ＆協業提案（{today}）\n{notion_url}\n\n{summary}",
        },
        timeout=30,
    )
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack 投稿失敗: {data.get('error')}")
    logger.info("Slack 投稿完了: %s", channel)


# ── エントリポイント ──────────────────────────────────────────────────────────

def main():
    today = datetime.now(JST).strftime("%Y-%m-%d")
    logger.info("=== 週次 人脈マップ＆協業提案レポート 開始 %s ===", today)

    notion = NotionClient(auth=os.environ["NOTION_TOKEN"])

    contacts = fetch_contacts(notion, DEFAULT_CONTACT_DATABASE_ID)
    cases = fetch_cases(notion, DEFAULT_CASE_DATABASE_ID)
    if not contacts:
        logger.info("コンタクトなし。終了。")
        return

    markdown = generate_report(contacts, cases, today)
    notion_url = create_notion_report(notion, markdown, today)
    post_to_slack(markdown, notion_url, today)
    logger.info("=== レポート完了 ===")


if __name__ == "__main__":
    main()
