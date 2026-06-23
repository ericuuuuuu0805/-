#!/usr/bin/env python3
"""
F2〜F4 で共有する補助関数。
Notion 案件DBの取得、Slack（Incoming Webhook）投稿、JST の日付ユーティリティ。
F1（update_notion_from_gmail.py）は独立稼働のため、ここには依存しない。
"""

import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from notion_client import Client as NotionClient

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

# Notion 案件DB（案件進捗（プロパー案件））。Secret 未設定時はコード内デフォルト。
DEFAULT_NOTION_DATABASE_ID = os.environ.get(
    "NOTION_DATABASE_ID", "c030de8d863640358e70b42f61de1318"
)


def today_jst() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d")


# ── Notion ───────────────────────────────────────────────────────────────────

def build_notion() -> NotionClient:
    return NotionClient(auth=os.environ["NOTION_TOKEN"])


def fetch_notion_cases(notion: NotionClient, database_id: str | None = None) -> list[dict]:
    """案件DBの全案件を取得する（F2〜F4で共通利用）。"""
    database_id = database_id or DEFAULT_NOTION_DATABASE_ID
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
                    # 設計書の「最終アクティビティ日」に相当（本DBでは『最終更新日』）
                    "最終更新日": _date(props, "最終更新日"),
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
    if t == "title":
        return "".join(r["plain_text"] for r in p.get("title", []) if isinstance(r, dict))
    return "".join(r["plain_text"] for r in p.get(t, []) if isinstance(r, dict)) if t else ""


def _select(props: dict, key: str) -> str:
    s = props.get(key, {}).get("select") or {}
    return s.get("name", "")


def _multi_select(props: dict, key: str) -> list[str]:
    return [s["name"] for s in props.get(key, {}).get("multi_select", [])]


def _date(props: dict, key: str) -> str:
    d = props.get(key, {}).get("date") or {}
    return d.get("start", "") or ""


def days_since(date_str: str) -> int | None:
    """date_str（YYYY-MM-DD 等）から本日(JST)までの経過日数。空なら None。"""
    if not date_str:
        return None
    try:
        d = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=JST)
    return (datetime.now(JST).date() - d.astimezone(JST).date()).days


# ── Slack（Incoming Webhook） ─────────────────────────────────────────────────

def post_to_slack(webhook_url: str, text: str) -> None:
    """Incoming Webhook にテキストを投稿する（mrkdwn）。"""
    if not webhook_url:
        raise ValueError("Slack Webhook URL が未設定です")

    payload = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            if body.strip() != "ok":
                logger.warning("Slack 応答が想定外: %s", body)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Slack 投稿失敗 ({e.code}): {detail}") from e

    logger.info("Slack 投稿完了（%d 文字）", len(text))
