#!/usr/bin/env python3
"""
Slack 全社連絡チャンネルから課題・決定事項を自動抽出するスクリプト。
週次目合わせダイジェスト（alignment_digest.py）の前段として実行される。

過去7日間の対象チャンネル（デフォルト: #general_全社連絡）のメッセージと
スレッド返信を読み取り、Claude が
- 会社としての課題（未登録のもの）
- 全社に共有された決定事項
を抽出して、Notion の 🔥 課題マップ / ✅ 目合わせログ に追加する。
既存の課題名・決定事項はプロンプトに渡して重複登録を防ぐ。
"""

import json
import logging
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import anthropic
from notion_client import Client as NotionClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

# 🔥 課題マップ
ISSUES_DATABASE_ID = os.environ.get(
    "ALIGNMENT_ISSUES_DATABASE_ID", "961640b0242c4178903f6c4a68f0fc53"
)
# ✅ 目合わせログ（決定事項）
DECISIONS_DATABASE_ID = os.environ.get(
    "ALIGNMENT_DECISIONS_DATABASE_ID", "45dfe17739634df693e1465052161eac"
)
# 抽出対象チャンネル（カンマ区切り。デフォルト: #general_全社連絡）
SLACK_CHANNEL_IDS = [
    c.strip()
    for c in os.environ.get("SLACK_CHANNEL_IDS", "C09HS0GF0SY").split(",")
    if c.strip()
]
LOOKBACK_DAYS = int(os.environ.get("ALIGNMENT_SLACK_LOOKBACK_DAYS", "7"))

ISSUE_CATEGORIES = [
    "収益モデル・契約",
    "プラント・保証・メンテ",
    "施工・営業体制",
    "ブランド・知財",
    "外部連携・資金",
    "組織・採用",
    "その他",
]


# ── Slack 読み取り ────────────────────────────────────────────────────────────

def _slack_api(method: str, params: dict) -> dict:
    token = os.environ["SLACK_BOT_TOKEN"]
    url = f"https://slack.com/api/{method}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as res:
        data = json.loads(res.read().decode("utf-8"))
    if not data.get("ok"):
        raise RuntimeError(f"Slack API {method} エラー: {data.get('error')}")
    return data


_user_cache: dict[str, str] = {}


def _user_name(user_id: str) -> str:
    if not user_id:
        return "unknown"
    if user_id not in _user_cache:
        try:
            data = _slack_api("users.info", {"user": user_id})
            profile = data["user"].get("profile", {})
            _user_cache[user_id] = (
                profile.get("display_name")
                or profile.get("real_name")
                or user_id
            )
        except Exception:
            _user_cache[user_id] = user_id
    return _user_cache[user_id]


def _channel_name(channel_id: str) -> str:
    try:
        data = _slack_api("conversations.info", {"channel": channel_id})
        return data["channel"]["name"]
    except Exception:
        return channel_id


def fetch_channel_messages(channel_id: str, days: int) -> list[dict]:
    oldest = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
    messages: list[dict] = []
    cursor = None

    while True:
        params = {"channel": channel_id, "oldest": f"{oldest:.6f}", "limit": 200}
        if cursor:
            params["cursor"] = cursor
        data = _slack_api("conversations.history", params)
        messages.extend(data.get("messages", []))
        cursor = data.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    # スレッド返信も取得（親メッセージが期間内のもの）
    replies: list[dict] = []
    for msg in messages:
        if msg.get("reply_count") and msg.get("thread_ts") == msg.get("ts"):
            data = _slack_api(
                "conversations.replies",
                {"channel": channel_id, "ts": msg["ts"], "limit": 100},
            )
            replies.extend(data.get("messages", [])[1:])  # 親は除外
            time.sleep(0.5)  # レートリミット対策

    all_messages = [
        m for m in messages + replies
        if m.get("type") == "message" and not m.get("subtype") and m.get("text")
    ]
    all_messages.sort(key=lambda m: float(m["ts"]))
    logger.info("チャンネル %s: %d 件のメッセージ", channel_id, len(all_messages))
    return all_messages


def format_messages(channel_id: str, messages: list[dict]) -> str:
    name = _channel_name(channel_id)
    lines = []
    for m in messages:
        ts = datetime.fromtimestamp(float(m["ts"]), JST).strftime("%Y-%m-%d %H:%M")
        author = _user_name(m.get("user", ""))
        lines.append(f"[{ts}] {author}:\n{m['text'][:2500]}")
    return f"### #{name}\n\n" + "\n\n---\n\n".join(lines)


# ── Notion 既存データ ─────────────────────────────────────────────────────────

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


def _title(page: dict, key: str) -> str:
    p = page["properties"].get(key, {})
    return "".join(r["plain_text"] for r in p.get("title", []))


def fetch_existing_titles(notion: NotionClient) -> tuple[list[str], list[str]]:
    issues = [_title(p, "課題名") for p in _query_all(notion, ISSUES_DATABASE_ID)]
    decisions = [
        _title(p, "決定事項") for p in _query_all(notion, DECISIONS_DATABASE_ID)
    ]
    logger.info("既存: 課題 %d 件 / 決定事項 %d 件", len(issues), len(decisions))
    return issues, decisions


# ── Claude 抽出 ───────────────────────────────────────────────────────────────

def extract_with_claude(
    slack_text: str, existing_issues: list[str], existing_decisions: list[str],
    today: str,
) -> dict:
    prompt = f"""あなたは株式会社温泉資源庁（Le Furo）の経営企画アシスタントです。
Slack の全社連絡チャンネルの過去{LOOKBACK_DAYS}日間の投稿から、
全社目合わせボードに載せるべき「会社としての課題」と「決定事項」を抽出してください。

今日の日付: {today}

## Slack メッセージ
{slack_text}

## 既に登録済みの課題（重複登録しない）
{json.dumps(existing_issues, ensure_ascii=False)}

## 既に登録済みの決定事項（重複登録しない）
{json.dumps(existing_decisions, ensure_ascii=False)}

## 抽出ルール
- 「課題」= 会社として対応・判断・議論が必要な未解決事項。
  個人のタスク、雑談、単なる情報共有、告知は含めない。
- 経営陣が「認識合わせしたい」「議論したい」と投げかけている論点は、
  ステータス「目合わせ待ち」の課題として抽出する。それ以外は「未着手」。
- 「決定事項」= 全社に向けて明確に決まったと報告されたこと。
- 既存リストと同じ・ほぼ同じ内容は抽出しない。
- 期限や日付が過ぎている告知は抽出しない。
- カテゴリは次から選ぶ: {json.dumps(ISSUE_CATEGORIES, ensure_ascii=False)}
- 確信が持てないものは含めない（過剰抽出より取りこぼしのほうがまし）。

## 出力形式（JSON のみ、説明不要）
{{
  "課題": [
    {{
      "課題名": "簡潔な課題名",
      "カテゴリ": "上記リストから1つ",
      "優先度": "🔴 高" | "🟡 中" | "🟢 低",
      "ステータス": "未着手" | "目合わせ待ち",
      "現状・論点": "Slack投稿に基づく現状と論点",
      "次アクション": "投稿から読み取れる次の一手（不明なら空文字）",
      "出典": "投稿者名と日付（例: Aya Ito 2026-06-04）"
    }}
  ],
  "決定事項": [
    {{
      "決定事項": "簡潔な決定内容",
      "決定日": "YYYY-MM-DD（投稿日）",
      "決定内容・背景": "投稿に基づく背景説明",
      "出典": "投稿者名と日付"
    }}
  ]
}}"""

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
    extracted = json.loads(raw)
    logger.info(
        "抽出結果: 課題 %d 件 / 決定事項 %d 件",
        len(extracted.get("課題", [])),
        len(extracted.get("決定事項", [])),
    )
    return extracted


# ── Notion 登録 ───────────────────────────────────────────────────────────────

def _rich_text_blocks(text: str) -> list[dict]:
    CHUNK = 1999
    return [
        {"type": "text", "text": {"content": text[i: i + CHUNK]}}
        for i in range(0, len(text), CHUNK)
    ] or [{"type": "text", "text": {"content": ""}}]


def register_issues(notion: NotionClient, issues: list[dict], channel_label: str):
    for issue in issues:
        category = issue.get("カテゴリ", "その他")
        if category not in ISSUE_CATEGORIES:
            category = "その他"
        status = issue.get("ステータス", "未着手")
        if status not in ("未着手", "目合わせ待ち"):
            status = "未着手"
        body = f"【Slack {channel_label} より自動抽出 / 出典: {issue.get('出典', '')}】\n{issue.get('現状・論点', '')}"

        notion.pages.create(
            parent={"database_id": ISSUES_DATABASE_ID},
            properties={
                "課題名": {"title": _rich_text_blocks(issue["課題名"])},
                "カテゴリ": {"select": {"name": category}},
                "優先度": {"select": {"name": issue.get("優先度", "🟡 中")}},
                "ステータス": {"select": {"name": status}},
                "現状・論点": {"rich_text": _rich_text_blocks(body)},
                "次アクション": {
                    "rich_text": _rich_text_blocks(issue.get("次アクション", ""))
                },
            },
        )
        logger.info("課題を登録: %s", issue["課題名"])


def register_decisions(
    notion: NotionClient, decisions: list[dict], channel_label: str, today: str
):
    for decision in decisions:
        body = f"【Slack {channel_label} より自動抽出 / 出典: {decision.get('出典', '')}】\n{decision.get('決定内容・背景', '')}"
        props: dict = {
            "決定事項": {"title": _rich_text_blocks(decision["決定事項"])},
            "決定内容・背景": {"rich_text": _rich_text_blocks(body)},
            # 全社連絡チャンネルで既に共有された内容のため
            "共有ステータス": {"select": {"name": "全社共有済み"}},
        }
        date = decision.get("決定日") or today
        props["決定日"] = {"date": {"start": date}}

        notion.pages.create(
            parent={"database_id": DECISIONS_DATABASE_ID}, properties=props
        )
        logger.info("決定事項を登録: %s", decision["決定事項"])


# ── エントリポイント ──────────────────────────────────────────────────────────

def main():
    today = datetime.now(JST).strftime("%Y-%m-%d")
    logger.info("=== Slack からの課題・決定事項抽出 開始 %s ===", today)

    if not os.environ.get("SLACK_BOT_TOKEN"):
        logger.warning("SLACK_BOT_TOKEN 未設定のため Slack 抽出をスキップします")
        return

    sections = []
    labels = []
    for channel_id in SLACK_CHANNEL_IDS:
        messages = fetch_channel_messages(channel_id, LOOKBACK_DAYS)
        if messages:
            sections.append(format_messages(channel_id, messages))
            labels.append(f"#{_channel_name(channel_id)}")

    if not sections:
        logger.info("対象期間のメッセージなし。終了。")
        return

    notion = NotionClient(auth=os.environ["NOTION_TOKEN"])
    existing_issues, existing_decisions = fetch_existing_titles(notion)

    extracted = extract_with_claude(
        "\n\n".join(sections), existing_issues, existing_decisions, today
    )

    channel_label = " / ".join(labels)
    register_issues(notion, extracted.get("課題", []), channel_label)
    register_decisions(notion, extracted.get("決定事項", []), channel_label, today)

    logger.info("=== 完了 ===")


if __name__ == "__main__":
    main()
