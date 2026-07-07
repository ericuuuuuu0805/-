#!/usr/bin/env python3
"""
毎週月曜日 9:00 JST に実行される「全社目合わせダイジェスト」自動生成スクリプト。

Notion の「全社目合わせボード」配下の3データベース
（🔥 課題マップ / 🏢 体制マップ / ✅ 目合わせログ）を読み取り、
- 目合わせ待ちの課題
- 高優先度で進行中の課題
- 長期間更新されていない課題（停滞アラート）
- 全社共有待ちの決定事項
- 立ち上げ中・構想段階の新体制
を集計し、Claude が全社向けの短いサマリーを書いて
ダッシュボードページの「📬 週次目合わせダイジェスト」セクションを更新する。

SLACK_WEBHOOK_URL が設定されていれば同じダイジェストを Slack にも投稿する。
"""

import json
import logging
import os
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

# 全社目合わせボード（ダッシュボードページ）
DASHBOARD_PAGE_ID = os.environ.get(
    "ALIGNMENT_DASHBOARD_PAGE_ID", "396ac6d8acb4811f8c09db8201519986"
)
# 🔥 課題マップ
ISSUES_DATABASE_ID = os.environ.get(
    "ALIGNMENT_ISSUES_DATABASE_ID", "961640b0242c4178903f6c4a68f0fc53"
)
# 🏢 体制マップ
TEAMS_DATABASE_ID = os.environ.get(
    "ALIGNMENT_TEAMS_DATABASE_ID", "2a2e7f1619304183851cae07a4dfd21d"
)
# ✅ 目合わせログ（決定事項）
DECISIONS_DATABASE_ID = os.environ.get(
    "ALIGNMENT_DECISIONS_DATABASE_ID", "45dfe17739634df693e1465052161eac"
)

# この日数以上更新のない未解決課題を「停滞」として扱う
STALE_DAYS = int(os.environ.get("ALIGNMENT_STALE_DAYS", "14"))

DIGEST_HEADING = "📬 週次目合わせダイジェスト"


# ── Notion 読み取り ──────────────────────────────────────────────────────────

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


def _rich_text(props: dict, key: str) -> str:
    p = props.get(key, {})
    t = p.get("type")
    return "".join(r["plain_text"] for r in p.get(t, []) if isinstance(r, dict))


def _select(props: dict, key: str) -> str:
    s = props.get(key, {}).get("select") or {}
    return s.get("name", "")


def _date(props: dict, key: str) -> str:
    d = props.get(key, {}).get("date") or {}
    return d.get("start", "")


def fetch_issues(notion: NotionClient) -> list[dict]:
    issues = []
    for page in _query_all(notion, ISSUES_DATABASE_ID):
        props = page["properties"]
        issues.append(
            {
                "url": page["url"],
                "課題名": _rich_text(props, "課題名"),
                "カテゴリ": _select(props, "カテゴリ"),
                "優先度": _select(props, "優先度"),
                "ステータス": _select(props, "ステータス"),
                "オーナー": _rich_text(props, "オーナー"),
                "期限": _date(props, "期限"),
                "現状・論点": _rich_text(props, "現状・論点"),
                "次アクション": _rich_text(props, "次アクション"),
                "最終更新": page.get("last_edited_time", ""),
            }
        )
    logger.info("課題マップ: %d 件", len(issues))
    return issues


def fetch_teams(notion: NotionClient) -> list[dict]:
    teams = []
    for page in _query_all(notion, TEAMS_DATABASE_ID):
        props = page["properties"]
        teams.append(
            {
                "url": page["url"],
                "チーム名": _rich_text(props, "チーム名"),
                "種別": _select(props, "種別"),
                "ステータス": _select(props, "ステータス"),
                "ミッション": _rich_text(props, "ミッション"),
                "責任者": _rich_text(props, "責任者"),
                "体制メモ": _rich_text(props, "体制メモ"),
            }
        )
    logger.info("体制マップ: %d 件", len(teams))
    return teams


def fetch_decisions(notion: NotionClient) -> list[dict]:
    decisions = []
    for page in _query_all(notion, DECISIONS_DATABASE_ID):
        props = page["properties"]
        decisions.append(
            {
                "url": page["url"],
                "決定事項": _rich_text(props, "決定事項"),
                "決定日": _date(props, "決定日"),
                "決定内容・背景": _rich_text(props, "決定内容・背景"),
                "共有ステータス": _select(props, "共有ステータス"),
            }
        )
    logger.info("目合わせログ: %d 件", len(decisions))
    return decisions


# ── 集計 ─────────────────────────────────────────────────────────────────────

def build_snapshot(issues: list[dict], teams: list[dict], decisions: list[dict]) -> dict:
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(days=STALE_DAYS)

    def is_stale(issue: dict) -> bool:
        if issue["ステータス"] == "解決済み" or not issue["最終更新"]:
            return False
        last = datetime.fromisoformat(issue["最終更新"].replace("Z", "+00:00"))
        return last < stale_before

    return {
        "目合わせ待ち": [i for i in issues if i["ステータス"] == "目合わせ待ち"],
        "高優先度_未解決": [
            i for i in issues
            if i["優先度"] == "🔴 高" and i["ステータス"] != "解決済み"
        ],
        "停滞課題": [i for i in issues if is_stale(i)],
        "共有待ち決定": [d for d in decisions if d["共有ステータス"] == "共有待ち"],
        "新体制": [t for t in teams if t["ステータス"] in ("立ち上げ中", "構想段階")],
        "課題総数": len(issues),
        "未解決課題数": len([i for i in issues if i["ステータス"] != "解決済み"]),
    }


# ── Claude サマリー ──────────────────────────────────────────────────────────

def summarize_with_claude(snapshot: dict, today: str) -> str:
    prompt = f"""あなたは株式会社温泉資源庁（Le Furo）の経営企画アシスタントです。
全社向けの「週次目合わせダイジェスト」の冒頭サマリーを書いてください。

今日の日付: {today}

## 現在のスナップショット（JSON）
{json.dumps(snapshot, ensure_ascii=False, indent=1, default=str)}

## 執筆ルール
- 全社員が30秒で読める分量（3〜5文、日本語）。
- 「今週、全社で目を合わせるべきこと」を最優先で書く（目合わせ待ちの課題、共有待ちの決定事項）。
- 停滞課題があれば名指しで注意喚起する。
- 事実のみ。スナップショットにない情報を創作しない。
- 前置きや挨拶は不要。本文のみ返す。"""

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    logger.info("Claude API を呼び出し中...")
    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


# ── ダイジェスト組み立て ──────────────────────────────────────────────────────

def _issue_line(i: dict) -> str:
    parts = [f"{i['優先度']} {i['課題名']}（{i['ステータス']}"]
    if i["オーナー"]:
        parts.append(f" / {i['オーナー']}")
    parts.append("）")
    if i["次アクション"]:
        parts.append(f" → {i['次アクション']}")
    return "".join(parts)


def build_digest_blocks(snapshot: dict, summary: str, today: str) -> list[dict]:
    def paragraph(text: str) -> dict:
        return {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": _rt(text)},
        }

    def heading3(text: str) -> dict:
        return {
            "object": "block",
            "type": "heading_3",
            "heading_3": {"rich_text": _rt(text)},
        }

    def bullet(text: str, url: str | None = None) -> dict:
        rich = _rt(text)
        if url:
            rich[0]["text"]["link"] = {"url": url}
        return {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": rich},
        }

    def _rt(text: str) -> list[dict]:
        CHUNK = 1999
        return [
            {"type": "text", "text": {"content": text[i: i + CHUNK]}}
            for i in range(0, len(text), CHUNK)
        ] or [{"type": "text", "text": {"content": ""}}]

    blocks: list[dict] = [
        {
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": _rt(f"【{today} 更新】{summary}"),
                "icon": {"type": "emoji", "emoji": "📣"},
                "color": "yellow_background",
            },
        },
        paragraph(
            f"未解決課題 {snapshot['未解決課題数']} 件 / 全 {snapshot['課題総数']} 件"
        ),
    ]

    sections = [
        ("🔺 目合わせ待ちの課題（次回ミーティングのアジェンダ）", snapshot["目合わせ待ち"]),
        ("🔴 高優先度で動いている課題", snapshot["高優先度_未解決"]),
        (f"🕰 {STALE_DAYS} 日以上更新のない課題（停滞アラート）", snapshot["停滞課題"]),
    ]
    for title, items in sections:
        blocks.append(heading3(title))
        if items:
            blocks.extend(bullet(_issue_line(i), i["url"]) for i in items)
        else:
            blocks.append(paragraph("なし 🎉"))

    blocks.append(heading3("✅ 全社共有待ちの決定事項"))
    if snapshot["共有待ち決定"]:
        blocks.extend(
            bullet(f"{d['決定事項']}（{d['決定日']} 決定）", d["url"])
            for d in snapshot["共有待ち決定"]
        )
    else:
        blocks.append(paragraph("なし"))

    blocks.append(heading3("🏢 立ち上げ中・構想段階の新体制"))
    if snapshot["新体制"]:
        blocks.extend(
            bullet(f"{t['チーム名']}（{t['ステータス']}）: {t['ミッション']}", t["url"])
            for t in snapshot["新体制"]
        )
    else:
        blocks.append(paragraph("なし"))

    return blocks


# ── ダッシュボード更新 ────────────────────────────────────────────────────────

def update_dashboard(notion: NotionClient, blocks: list[dict]):
    """「📬 週次目合わせダイジェスト」見出し以降のブロックを新しい内容に差し替える。
    見出しはページ本文の最終セクションである前提（子データベースブロックは残す）。
    """
    children: list[dict] = []
    cursor = None
    while True:
        kwargs: dict = {"block_id": DASHBOARD_PAGE_ID, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        result = notion.blocks.children.list(**kwargs)
        children.extend(result["results"])
        if not result.get("has_more"):
            break
        cursor = result.get("next_cursor")

    heading_index = None
    for idx, block in enumerate(children):
        if block["type"].startswith("heading"):
            texts = block[block["type"]].get("rich_text", [])
            plain = "".join(t.get("plain_text", "") for t in texts)
            if DIGEST_HEADING in plain:
                heading_index = idx
                break

    if heading_index is None:
        raise RuntimeError(
            f"ダッシュボードに見出し「{DIGEST_HEADING}」が見つかりません"
        )

    # 見出しの後ろの旧ダイジェスト（子DBブロック以外）を削除
    for block in children[heading_index + 1:]:
        if block["type"] in ("child_database", "child_page"):
            continue
        notion.blocks.delete(block_id=block["id"])

    # 新しいダイジェストを見出しの直後に挿入
    notion.blocks.children.append(
        block_id=DASHBOARD_PAGE_ID,
        children=blocks,
        after=children[heading_index]["id"],
    )
    logger.info("ダッシュボードのダイジェストを更新しました")


# ── Slack 通知（任意） ────────────────────────────────────────────────────────

def post_to_slack(snapshot: dict, summary: str, today: str):
    webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook:
        logger.info("SLACK_WEBHOOK_URL 未設定のため Slack 通知はスキップ")
        return

    lines = [f"*📬 週次目合わせダイジェスト（{today}）*", "", summary, ""]
    if snapshot["目合わせ待ち"]:
        lines.append("*🔺 目合わせ待ちの課題*")
        lines.extend(f"• {_issue_line(i)}" for i in snapshot["目合わせ待ち"])
    if snapshot["停滞課題"]:
        lines.append(f"*🕰 {STALE_DAYS} 日以上更新のない課題*")
        lines.extend(f"• {i['課題名']}" for i in snapshot["停滞課題"])
    lines.append("")
    lines.append(
        f"詳細: https://app.notion.com/p/{DASHBOARD_PAGE_ID.replace('-', '')}"
    )

    payload = json.dumps({"text": "\n".join(lines)}).encode("utf-8")
    req = urllib.request.Request(
        webhook, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        logger.info("Slack 通知完了: HTTP %d", res.status)


# ── エントリポイント ──────────────────────────────────────────────────────────

def main():
    today = datetime.now(JST).strftime("%Y-%m-%d")
    logger.info("=== 週次目合わせダイジェスト生成 開始 %s ===", today)

    notion = NotionClient(auth=os.environ["NOTION_TOKEN"])

    issues = fetch_issues(notion)
    teams = fetch_teams(notion)
    decisions = fetch_decisions(notion)

    snapshot = build_snapshot(issues, teams, decisions)
    summary = summarize_with_claude(snapshot, today)

    blocks = build_digest_blocks(snapshot, summary, today)
    update_dashboard(notion, blocks)
    post_to_slack(snapshot, summary, today)

    logger.info("=== 完了 ===")


if __name__ == "__main__":
    main()
