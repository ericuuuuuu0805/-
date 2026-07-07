#!/usr/bin/env python3
"""
Slack の人脈メモチャンネルを読み取り、Notion「👥 コンタクト（人脈マップ）」DB へ
自動登録するスクリプト。

三田さん・新井さん・小村さんがチャンネルに
「昨日◯◯社の△△さんと会った。□□に興味あり」のように書くだけで、
Claude が構造化してコンタクトDBに登録（既存人物なら追記）する。
"""

import json
import logging
import os
import time
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

# Notion database ID（👥 コンタクト（人脈マップ））
DEFAULT_CONTACT_DATABASE_ID = os.environ.get(
    "CONTACT_DATABASE_ID", "cb82f51a87b547debf1583e7b0dc1c24"
)

事業群の選択肢 = [
    "喫泉室", "プラント", "受託製造", "業務提携", "スパ",
    "卸", "飲料", "研究・医療", "行政・団体", "その他",
]
関係ステータスの選択肢 = [
    "初回接触", "関係構築中", "案件化", "既存顧客",
    "紹介元・キーパーソン", "休眠",
]
担当の選択肢 = ["三田", "新井", "小村", "エリック", "松本"]


# ── Slack ────────────────────────────────────────────────────────────────────

def slack_api(method: str, token: str, **params) -> dict:
    resp = requests.get(
        f"https://slack.com/api/{method}",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=30,
    )
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack API {method} 失敗: {data.get('error')}")
    return data


def fetch_recent_messages(token: str, channel_id: str, days: int = 7) -> list[dict]:
    oldest = (datetime.now(JST) - timedelta(days=days)).timestamp()
    messages: list[dict] = []
    cursor = None
    user_names: dict[str, str] = {}

    while True:
        params = {"channel": channel_id, "oldest": oldest, "limit": 200}
        if cursor:
            params["cursor"] = cursor
        data = slack_api("conversations.history", token, **params)

        for msg in data.get("messages", []):
            if msg.get("subtype") or msg.get("bot_id"):
                continue  # bot 投稿・システムメッセージは対象外
            uid = msg.get("user", "")
            if uid and uid not in user_names:
                try:
                    info = slack_api("users.info", token, user=uid)
                    user_names[uid] = info["user"]["profile"].get(
                        "real_name"
                    ) or info["user"].get("name", uid)
                    time.sleep(0.3)
                except Exception:
                    user_names[uid] = uid
            ts = float(msg["ts"])
            messages.append(
                {
                    "投稿者": user_names.get(uid, uid),
                    "日時": datetime.fromtimestamp(ts, JST).strftime("%Y-%m-%d %H:%M"),
                    "本文": msg.get("text", ""),
                }
            )

        cursor = data.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    messages.reverse()  # 古い順
    logger.info("取得メッセージ数: %d 件", len(messages))
    return messages


# ── Notion ───────────────────────────────────────────────────────────────────

def fetch_existing_contacts(notion: NotionClient, database_id: str) -> list[dict]:
    contacts: list[dict] = []
    cursor = None
    while True:
        kwargs: dict = {"database_id": database_id, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        result = notion.databases.query(**kwargs)
        for page in result["results"]:
            props = page["properties"]
            contacts.append(
                {
                    "id": page["id"],
                    "名前": _title(props, "名前"),
                    "会社・組織": _rich_text(props, "会社・組織"),
                }
            )
        if not result.get("has_more"):
            break
        cursor = result.get("next_cursor")
    logger.info("既存コンタクト数: %d 件", len(contacts))
    return contacts


def _title(props: dict, key: str) -> str:
    return "".join(r["plain_text"] for r in props.get(key, {}).get("title", []))


def _rich_text(props: dict, key: str) -> str:
    return "".join(r["plain_text"] for r in props.get(key, {}).get("rich_text", []))


# ── Claude 分析 ───────────────────────────────────────────────────────────────

def extract_with_claude(
    messages: list[dict], contacts: list[dict], today: str
) -> list[dict]:
    contacts_text = "\n".join(
        f"- id={c['id']} | {c['名前']} | {c['会社・組織']}" for c in contacts
    )
    messages_text = "\n\n---\n\n".join(
        f"【投稿者】{m['投稿者']}\n【日時】{m['日時']}\n【本文】{m['本文']}"
        for m in messages
    )

    prompt = f"""あなたは株式会社温泉資源庁（Le Furo）の人脈管理アシスタントです。
Slack の人脈メモチャンネルの投稿から、会った人・接触した人の情報を抽出し、
Notion コンタクトDBへの登録内容を JSON で返してください。

今日の日付: {today}

## 既存コンタクト一覧（重複チェック用）
{contacts_text}

## Slack 投稿（過去7日間）
{messages_text}

## ルール
- 人物への言及がある投稿のみ対象。雑談・業務連絡はスキップ。
- 既存コンタクトと同一人物（名前と会社が一致・表記ゆれ含む）の場合は "page_id" を指定し、
  新情報のみを "メモ_追記" に書く（既存メモは消さずスクリプト側で追記する）。
- 新規人物は "page_id" を null にして全項目をできるだけ埋める。不明な項目は null。
- "事業群" は {事業群の選択肢} から複数選択。
- "関係ステータス" は {関係ステータスの選択肢} から1つ。新規に会っただけなら「初回接触」。
- "担当" は {担当の選択肢} から該当者（投稿者本人を含めてよい）。
- "初回接触日" は投稿から読み取れる実際に会った日（YYYY-MM-DD）。不明なら投稿日。

## 出力形式（JSON のみ）
[
  {{
    "page_id": null または "既存ページID",
    "名前": "姓 名",
    "会社・組織": "会社名",
    "役職・部署": null,
    "事業群": ["卸"],
    "関係ステータス": "初回接触",
    "担当": ["三田"],
    "初回接触日": "YYYY-MM-DD",
    "接触経緯": "どこで・誰の紹介で会ったか",
    "メール": null,
    "メモ_追記": "投稿から読み取れる補足情報"
  }}
]

抽出対象がなければ [] を返してください。JSON のみ返答してください。"""

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    logger.info("Claude API を呼び出し中...")

    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

    entries = json.loads(raw)
    logger.info("Claude が %d 件のコンタクトを抽出", len(entries))
    return entries


# ── Notion 登録 ───────────────────────────────────────────────────────────────

def _rt(text: str) -> dict:
    return {"rich_text": [{"type": "text", "text": {"content": text[:1999]}}]}


def apply_entries(notion: NotionClient, entries: list[dict], database_id: str, today: str):
    created = updated = 0
    for e in entries:
        try:
            if e.get("page_id"):
                # 既存コンタクトへの追記
                page = notion.pages.retrieve(page_id=e["page_id"])
                existing = "".join(
                    b.get("plain_text", "")
                    for b in page["properties"].get("メモ", {}).get("rich_text", [])
                )
                addition = e.get("メモ_追記") or ""
                new_memo = (
                    f"{existing}\n【{today} Slackより】{addition}"
                    if existing.strip()
                    else f"【{today} Slackより】{addition}"
                )
                notion.pages.update(
                    page_id=e["page_id"],
                    properties={
                        "メモ": _rt(new_memo),
                        "最終接触日": {"date": {"start": today}},
                    },
                )
                updated += 1
                logger.info("追記: %s", e.get("名前"))
            else:
                props: dict = {
                    "名前": {"title": [{"type": "text", "text": {"content": e["名前"]}}]},
                    "関係ステータス": {
                        "select": {"name": e.get("関係ステータス") or "初回接触"}
                    },
                    "情報ソース": {"multi_select": [{"name": "Slack"}]},
                }
                if e.get("会社・組織"):
                    props["会社・組織"] = _rt(e["会社・組織"])
                if e.get("役職・部署"):
                    props["役職・部署"] = _rt(e["役職・部署"])
                if e.get("事業群"):
                    props["事業群"] = {
                        "multi_select": [
                            {"name": s} for s in e["事業群"] if s in 事業群の選択肢
                        ]
                    }
                if e.get("担当"):
                    props["担当"] = {
                        "multi_select": [
                            {"name": s} for s in e["担当"] if s in 担当の選択肢
                        ]
                    }
                if e.get("初回接触日"):
                    props["初回接触日"] = {"date": {"start": e["初回接触日"]}}
                    props["最終接触日"] = {"date": {"start": e["初回接触日"]}}
                if e.get("接触経緯"):
                    props["接触経緯"] = _rt(e["接触経緯"])
                if e.get("メール"):
                    props["メール"] = {"email": e["メール"]}
                if e.get("メモ_追記"):
                    props["メモ"] = _rt(e["メモ_追記"])

                notion.pages.create(
                    parent={"database_id": database_id}, properties=props
                )
                created += 1
                logger.info("新規登録: %s（%s）", e.get("名前"), e.get("会社・組織"))
        except Exception:
            logger.exception("登録失敗: %s", e.get("名前"))

    logger.info("新規 %d 件 / 追記 %d 件", created, updated)


# ── エントリポイント ──────────────────────────────────────────────────────────

def main():
    today = datetime.now(JST).strftime("%Y-%m-%d")
    logger.info("=== Slack→コンタクトDB 同期 開始 %s ===", today)

    slack_token = os.environ["SLACK_BOT_TOKEN"]
    channel_id = os.environ["SLACK_CONTACT_CHANNEL_ID"]
    notion = NotionClient(auth=os.environ["NOTION_TOKEN"])
    database_id = DEFAULT_CONTACT_DATABASE_ID

    messages = fetch_recent_messages(slack_token, channel_id, days=7)
    if not messages:
        logger.info("過去7日間の投稿なし。終了。")
        return

    contacts = fetch_existing_contacts(notion, database_id)
    entries = extract_with_claude(messages, contacts, today)
    if not entries:
        logger.info("抽出対象なし。終了。")
        return

    apply_entries(notion, entries, database_id, today)
    logger.info("=== 同期完了 ===")


if __name__ == "__main__":
    main()
