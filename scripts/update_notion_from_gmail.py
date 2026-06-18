#!/usr/bin/env python3
"""
毎週金曜日 10:00 JST に実行される Notion 案件進捗自動更新スクリプト。
過去7日間の Gmail（温泉資源庁 Eric Le Furo アカウント）を読み取り、
Notion 案件進捗（プロパー案件）データベースの各案件を更新する。
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import anthropic
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from notion_client import Client as NotionClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

# Notion database page ID（案件進捗（プロパー案件））
DEFAULT_NOTION_DATABASE_ID = os.environ.get(
    "NOTION_DATABASE_ID", "c030de8d863640358e70b42f61de1318"
)


# ── Gmail ────────────────────────────────────────────────────────────────────

def build_gmail_service():
    token_json = os.environ.get("GMAIL_TOKEN_JSON")
    if not token_json:
        raise ValueError("環境変数 GMAIL_TOKEN_JSON が未設定です")
    creds = Credentials.from_authorized_user_info(json.loads(token_json))
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def fetch_recent_emails(service, days: int = 7) -> list[dict]:
    after_date = (datetime.now(JST) - timedelta(days=days)).strftime("%Y/%m/%d")
    query = f"after:{after_date}"
    logger.info("Gmail 検索クエリ: %s", query)

    emails: list[dict] = []
    page_token = None

    while True:
        result = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=200, pageToken=page_token)
            .execute()
        )
        for msg in result.get("messages", []):
            detail = (
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=msg["id"],
                    format="full",
                )
                .execute()
            )
            headers = {
                h["name"]: h["value"]
                for h in detail["payload"].get("headers", [])
            }
            body = _extract_body(detail["payload"])
            emails.append(
                {
                    "id": msg["id"],
                    "subject": headers.get("Subject", ""),
                    "from": headers.get("From", ""),
                    "to": headers.get("To", ""),
                    "date": headers.get("Date", ""),
                    "snippet": detail.get("snippet", ""),
                    "body": body[:3000],
                }
            )
        page_token = result.get("nextPageToken")
        if not page_token:
            break

    logger.info("取得メール数: %d 件", len(emails))
    return emails


def _extract_body(payload: dict) -> str:
    import base64

    parts = payload.get("parts", [])
    if not parts:
        data = payload.get("body", {}).get("data", "")
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore") if data else ""

    for part in parts:
        if part.get("mimeType") == "text/plain":
            data = part.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")
    return ""


# ── Notion ───────────────────────────────────────────────────────────────────

def fetch_notion_cases(notion: NotionClient, database_id: str) -> list[dict]:
    cases: list[dict] = []
    cursor = None

    while True:
        kwargs: dict = {"database_id": database_id, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor

        result = notion.databases.query(**kwargs)

        for page in result["results"]:
            props = page["properties"]
            cases.append(
                {
                    "id": page["id"],
                    "url": page["url"],
                    "案件名": _rich_text(props, "案件名"),
                    "企業名": _rich_text(props, "企業名"),
                    "カテゴリー": _multi_select(props, "カテゴリー"),
                    "優先度": _select(props, "優先度"),
                    "現状": _rich_text(props, "現状"),
                    "次アクション": _rich_text(props, "次アクション"),
                }
            )

        if not result.get("has_more"):
            break
        cursor = result.get("next_cursor")

    logger.info("Notion 案件数: %d 件", len(cases))
    return cases


def _rich_text(props: dict, key: str) -> str:
    p = props.get(key, {})
    t = p.get("type")
    return "".join(r["plain_text"] for r in p.get(t, []) if isinstance(r, dict))


def _select(props: dict, key: str) -> str:
    s = props.get(key, {}).get("select") or {}
    return s.get("name", "")


def _multi_select(props: dict, key: str) -> list[str]:
    return [s["name"] for s in props.get(key, {}).get("multi_select", [])]


# ── Claude 分析 ───────────────────────────────────────────────────────────────

def analyze_with_claude(
    emails: list[dict], cases: list[dict], today: str
) -> list[dict]:
    cases_text = "\n\n".join(
        f"【案件ID】{c['id']}\n【企業名】{c['企業名']}\n【案件名】{c['案件名']}\n"
        f"【カテゴリー】{', '.join(c['カテゴリー'])}\n【優先度】{c['優先度']}\n"
        f"【現状（直近200字）】{c['現状'][-200:]}"
        for c in cases
    )

    emails_text = "\n\n---\n\n".join(
        f"【日付】{e['date']}\n【件名】{e['subject']}\n"
        f"【From】{e['from']}\n【To】{e['to']}\n"
        f"【本文抜粋】{(e['body'] or e['snippet'])[:1500]}"
        for e in emails
    )

    prompt = f"""あなたは株式会社温泉資源庁（Le Furo）の営業進捗管理アシスタントです。
社長エリック・ミラー（eric@le-furo.com / lefuro0805@gmail.com）の Gmail を分析し、
Notion の案件進捗を更新してください。

今日の日付: {today}

## Notion 案件一覧
{cases_text}

## 過去7日間の Gmail
{emails_text}

## 厳守ルール
- 既存の「現状」フィールドの内容は**絶対に消去・変更しない**。
- 追記するのは、既存の「現状」に記載されていない**新規情報のみ**。
- 返す「現状_追記」は追記分だけを書く（既存文を含めない）。
  スクリプト側で「既存文 ＋ 空行 ＋ 追記」の順で結合するので、既存文の繰り返しは不要。
- 関連するメールがない案件や、既に現状に記録済みの内容のみの案件は含めないでください。

## 出力形式（JSON のみ）
[
  {{
    "page_id": "Notion ページ ID（ハイフンなし）",
    "現状_追記": "【{today} 更新】\\n具体的な進捗内容（追記分のみ）",
    "関連メール件名": "件名"
  }}
]

JSON のみ返答してください。説明は不要です。"""

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    logger.info("Claude API を呼び出し中...")

    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

    updates = json.loads(raw)
    logger.info("Claude が %d 件の更新を提案", len(updates))
    return updates


# ── Notion 更新 ───────────────────────────────────────────────────────────────

def _to_rich_text_blocks(text: str) -> list[dict]:
    """Notion rich_text は1ブロック最大2000文字のため分割する。"""
    CHUNK = 1999
    return [
        {"type": "text", "text": {"content": text[i: i + CHUNK]}}
        for i in range(0, len(text), CHUNK)
    ] or [{"type": "text", "text": {"content": ""}}]


def apply_updates(
    notion: NotionClient, updates: list[dict], cases: list[dict], today: str
):
    case_map = {c["id"].replace("-", ""): c for c in cases}
    case_map.update({c["id"]: c for c in cases})

    for upd in updates:
        pid = upd["page_id"]
        case = case_map.get(pid) or case_map.get(pid.replace("-", ""))
        if not case:
            logger.warning("案件が見つかりません: %s", pid)
            continue

        # 書き込み直前に最新の現状を再取得（手動編集との競合を防ぐ）
        live_page = notion.pages.retrieve(page_id=case["id"])
        live_props = live_page.get("properties", {})
        existing_blocks = live_props.get("現状", {}).get("rich_text", [])
        existing = "".join(b.get("plain_text", "") for b in existing_blocks)

        addition = upd["現状_追記"]

        # 既存内容は絶対に保持し、末尾に追記のみ行う
        new_text = f"{existing}\n\n{addition}" if existing.strip() else addition

        notion.pages.update(
            page_id=case["id"],
            properties={
                "現状": {"rich_text": _to_rich_text_blocks(new_text)},
                "最終更新日": {"date": {"start": today}},
            },
        )
        logger.info(
            "更新完了: %s - %s（関連メール: %s）",
            case["企業名"],
            case["案件名"],
            upd.get("関連メール件名", ""),
        )


# ── エントリポイント ──────────────────────────────────────────────────────────

def main():
    today = datetime.now(JST).strftime("%Y-%m-%d")
    logger.info("=== 毎週 Notion 案件進捗更新 開始 %s ===", today)

    gmail = build_gmail_service()
    notion = NotionClient(auth=os.environ["NOTION_TOKEN"])
    database_id = DEFAULT_NOTION_DATABASE_ID

    emails = fetch_recent_emails(gmail, days=7)
    if not emails:
        logger.info("過去7日間のメールなし。終了。")
        return

    cases = fetch_notion_cases(notion, database_id)
    updates = analyze_with_claude(emails, cases, today)

    if not updates:
        logger.info("更新対象の案件なし。終了。")
        return

    apply_updates(notion, updates, cases, today)
    logger.info("=== 更新完了: %d 件 ===", len(updates))


if __name__ == "__main__":
    main()
