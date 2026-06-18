"""Fetches project and meeting note data from Notion for the current week."""

import os
from datetime import datetime, timedelta, timezone
from notion_client import Client


JST = timezone(timedelta(hours=9))


def get_week_range() -> tuple[str, str]:
    now = datetime.now(JST)
    # Monday of current week
    monday = now - timedelta(days=now.weekday())
    start = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    end = now
    return start.isoformat(), end.isoformat()


def fetch_projects(notion: Client, db_id: str) -> list[dict]:
    """Fetch all project records updated this week."""
    start_date, end_date = get_week_range()
    results = []
    cursor = None

    while True:
        kwargs = {
            "database_id": db_id,
            "filter": {
                "or": [
                    {
                        "property": "最終更新日時",
                        "date": {"on_or_after": start_date}
                    },
                    {
                        "property": "last_edited_time",
                        "date": {"on_or_after": start_date}
                    }
                ]
            },
            "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}]
        }
        if cursor:
            kwargs["start_cursor"] = cursor

        response = notion.databases.query(**kwargs)
        results.extend(response.get("results", []))

        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")

    return results


def fetch_all_projects(notion: Client, db_id: str) -> list[dict]:
    """Fetch all projects to check which ones had no activity."""
    results = []
    cursor = None

    while True:
        kwargs = {"database_id": db_id}
        if cursor:
            kwargs["start_cursor"] = cursor

        response = notion.databases.query(**kwargs)
        results.extend(response.get("results", []))

        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")

    return results


def fetch_meeting_notes(notion: Client, db_id: str) -> list[dict]:
    """Fetch meeting notes created this week."""
    start_date, _ = get_week_range()
    results = []
    cursor = None

    while True:
        kwargs = {
            "database_id": db_id,
            "filter": {
                "or": [
                    {
                        "property": "日付",
                        "date": {"on_or_after": start_date[:10]}
                    },
                    {
                        "property": "Date",
                        "date": {"on_or_after": start_date[:10]}
                    }
                ]
            },
            "sorts": [{"property": "日付", "direction": "descending"}]
        }
        if cursor:
            kwargs["start_cursor"] = cursor

        try:
            response = notion.databases.query(**kwargs)
        except Exception:
            # Try without date filter if property name is different
            kwargs_simple = {"database_id": db_id}
            if cursor:
                kwargs_simple["start_cursor"] = cursor
            response = notion.databases.query(**kwargs_simple)

        results.extend(response.get("results", []))

        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")

    return results


def extract_page_text(notion: Client, page_id: str, max_blocks: int = 50) -> str:
    """Extract plain text content from a Notion page."""
    try:
        blocks = notion.blocks.children.list(block_id=page_id, page_size=max_blocks)
        texts = []
        for block in blocks.get("results", []):
            block_type = block.get("type", "")
            block_data = block.get(block_type, {})
            rich_texts = block_data.get("rich_text", [])
            for rt in rich_texts:
                texts.append(rt.get("plain_text", ""))
        return "\n".join(texts)
    except Exception:
        return ""


def extract_property_value(prop: dict) -> str:
    """Extract readable value from a Notion property."""
    ptype = prop.get("type", "")

    if ptype == "title":
        items = prop.get("title", [])
        return "".join(t.get("plain_text", "") for t in items)

    if ptype == "rich_text":
        items = prop.get("rich_text", [])
        return "".join(t.get("plain_text", "") for t in items)

    if ptype == "select":
        sel = prop.get("select")
        return sel.get("name", "") if sel else ""

    if ptype == "multi_select":
        items = prop.get("multi_select", [])
        return ", ".join(i.get("name", "") for i in items)

    if ptype == "status":
        status = prop.get("status")
        return status.get("name", "") if status else ""

    if ptype == "date":
        date = prop.get("date")
        if date:
            start = date.get("start", "")
            end = date.get("end", "")
            return f"{start} ～ {end}" if end else start
        return ""

    if ptype == "people":
        people = prop.get("people", [])
        return ", ".join(p.get("name", p.get("id", "")) for p in people)

    if ptype == "url":
        return prop.get("url", "") or ""

    if ptype == "email":
        return prop.get("email", "") or ""

    if ptype == "phone_number":
        return prop.get("phone_number", "") or ""

    if ptype == "number":
        val = prop.get("number")
        return str(val) if val is not None else ""

    if ptype == "checkbox":
        return "✓" if prop.get("checkbox") else "✗"

    if ptype == "formula":
        formula = prop.get("formula", {})
        ftype = formula.get("type", "")
        return str(formula.get(ftype, ""))

    if ptype in ("created_time", "last_edited_time"):
        return prop.get(ptype, "")

    return ""


def page_to_dict(page: dict) -> dict:
    """Convert a Notion page to a simplified dictionary."""
    props = page.get("properties", {})
    result = {"page_id": page["id"]}
    for key, value in props.items():
        extracted = extract_property_value(value)
        if extracted:
            result[key] = extracted
    return result


def build_notion_context(api_key: str, projects_db_id: str, meeting_db_id: str) -> dict:
    notion = Client(auth=api_key)

    week_projects_raw = fetch_projects(notion, projects_db_id)
    all_projects_raw = fetch_all_projects(notion, projects_db_id)
    meeting_notes_raw = fetch_meeting_notes(notion, meeting_db_id)

    week_project_ids = {p["id"] for p in week_projects_raw}

    week_projects = []
    for page in week_projects_raw:
        p = page_to_dict(page)
        content = extract_page_text(notion, page["id"])
        if content:
            p["_page_content"] = content[:1000]
        week_projects.append(p)

    inactive_projects = [
        page_to_dict(p) for p in all_projects_raw if p["id"] not in week_project_ids
    ]

    meeting_notes = []
    for page in meeting_notes_raw:
        m = page_to_dict(page)
        content = extract_page_text(notion, page["id"])
        if content:
            m["_page_content"] = content[:1500]
        meeting_notes.append(m)

    return {
        "week_projects": week_projects,
        "inactive_projects": inactive_projects,
        "meeting_notes": meeting_notes,
    }
