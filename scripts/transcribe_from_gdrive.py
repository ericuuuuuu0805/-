#!/usr/bin/env python3
"""
Google Drive の指定フォルダにある録音ファイルを自動で文字起こし（OpenAI Whisper）し、
Notion データベースにページとして保存するスクリプト。
処理済みファイルは同フォルダ内の「済み」サブフォルダに移動される。

必要な環境変数:
  GDRIVE_TOKEN_JSON                - Google Drive OAuth2 トークン（JSON 文字列）
  GDRIVE_AUDIO_FOLDER_ID           - 録音ファイルを置く Google Drive フォルダ ID
  OPENAI_API_KEY                   - OpenAI API キー（Whisper 使用）
  NOTION_TOKEN                     - Notion インテグレーション トークン
  NOTION_TRANSCRIPTION_DATABASE_ID - 保存先 Notion データベース ID
"""

import io
import json
import logging
import os
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from notion_client import Client as NotionClient
from openai import OpenAI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

GDRIVE_FOLDER_ID = os.environ.get("GDRIVE_AUDIO_FOLDER_ID", "")
NOTION_TRANSCRIPTION_DB_ID = os.environ.get("NOTION_TRANSCRIPTION_DATABASE_ID", "")
PROCESSED_FOLDER_NAME = "済み"
MAX_FILE_SIZE = 25 * 1024 * 1024  # Whisper の上限 25MB
AUDIO_EXTENSIONS = {".m4a", ".mp3", ".mp4", ".wav", ".aac", ".ogg", ".webm", ".flac", ".mpga"}


# ── Google Drive ──────────────────────────────────────────────────────────────

def build_gdrive_service():
    token_json = os.environ.get("GDRIVE_TOKEN_JSON")
    if not token_json:
        raise ValueError("環境変数 GDRIVE_TOKEN_JSON が未設定です")
    creds = Credentials.from_authorized_user_info(
        json.loads(token_json),
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def get_or_create_processed_folder(service, parent_folder_id: str) -> str:
    query = (
        f"'{parent_folder_id}' in parents "
        f"and name = '{PROCESSED_FOLDER_NAME}' "
        f"and mimeType = 'application/vnd.google-apps.folder' "
        f"and trashed = false"
    )
    result = service.files().list(q=query, fields="files(id)").execute()
    files = result.get("files", [])
    if files:
        return files[0]["id"]

    folder = service.files().create(
        body={
            "name": PROCESSED_FOLDER_NAME,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_folder_id],
        },
        fields="id",
    ).execute()
    logger.info("処理済みフォルダを作成: %s", folder["id"])
    return folder["id"]


def list_audio_files(service, folder_id: str) -> list[dict]:
    query = (
        f"'{folder_id}' in parents "
        f"and mimeType != 'application/vnd.google-apps.folder' "
        f"and trashed = false"
    )
    result = service.files().list(
        q=query,
        fields="files(id, name, mimeType, size, createdTime)",
        orderBy="createdTime",
    ).execute()

    all_files = result.get("files", [])
    audio_files = [
        f for f in all_files
        if Path(f["name"]).suffix.lower() in AUDIO_EXTENSIONS
        or f.get("mimeType", "").startswith("audio/")
    ]
    logger.info("録音ファイル数: %d 件", len(audio_files))
    return audio_files


def download_audio(service, file_id: str) -> bytes:
    request = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


def move_to_processed(service, file_id: str, parent_id: str, processed_id: str):
    service.files().update(
        fileId=file_id,
        addParents=processed_id,
        removeParents=parent_id,
        fields="id, parents",
    ).execute()


# ── OpenAI Whisper ────────────────────────────────────────────────────────────

def transcribe(audio_bytes: bytes, filename: str, client: OpenAI) -> str:
    suffix = Path(filename).suffix.lower() or ".m4a"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name
    try:
        with open(tmp_path, "rb") as f:
            response = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                language="ja",
            )
        return response.text
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ── Notion ────────────────────────────────────────────────────────────────────

def save_transcription(
    notion: NotionClient,
    database_id: str,
    filename: str,
    transcription: str,
    gdrive_file_id: str,
    recorded_at: str,
):
    page = notion.pages.create(
        parent={"database_id": database_id},
        properties={
            "ファイル名": {
                "title": [{"type": "text", "text": {"content": filename}}]
            },
            "録音日時": {
                "date": {"start": recorded_at[:10]}
            },
            "Google DriveファイルID": {
                "rich_text": [{"type": "text", "text": {"content": gdrive_file_id}}]
            },
        },
    )

    # 本文として段落ブロックに書き込む（2000文字/ブロック）
    CHUNK = 1999
    children = [
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {"type": "text", "text": {"content": transcription[i: i + CHUNK]}}
                ]
            },
        }
        for i in range(0, len(transcription), CHUNK)
    ] or [
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": "（文字起こし結果なし）"}}]},
        }
    ]

    # Notion API は 1 回に 100 ブロックまで
    for i in range(0, len(children), 100):
        notion.blocks.children.append(block_id=page["id"], children=children[i: i + 100])

    logger.info("Notion 保存完了: %s (page_id: %s)", filename, page["id"])


# ── エントリポイント ──────────────────────────────────────────────────────────

def main():
    today = datetime.now(JST).strftime("%Y-%m-%d")
    logger.info("=== 録音文字起こし開始 %s ===", today)

    if not GDRIVE_FOLDER_ID:
        raise ValueError("環境変数 GDRIVE_AUDIO_FOLDER_ID が未設定です")
    if not NOTION_TRANSCRIPTION_DB_ID:
        raise ValueError("環境変数 NOTION_TRANSCRIPTION_DATABASE_ID が未設定です")

    drive = build_gdrive_service()
    notion = NotionClient(auth=os.environ["NOTION_TOKEN"])
    openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    processed_folder_id = get_or_create_processed_folder(drive, GDRIVE_FOLDER_ID)

    audio_files = list_audio_files(drive, GDRIVE_FOLDER_ID)
    if not audio_files:
        logger.info("処理対象ファイルなし。終了。")
        return

    success = 0
    for audio in audio_files:
        file_id = audio["id"]
        filename = audio["name"]
        recorded_at = audio.get("createdTime", today)
        file_size = int(audio.get("size", 0))

        if file_size > MAX_FILE_SIZE:
            logger.warning("サイズ超過のためスキップ: %s (%d MB)", filename, file_size // 1024 // 1024)
            continue

        logger.info("処理中: %s", filename)
        try:
            audio_bytes = download_audio(drive, file_id)
            logger.info("ダウンロード完了: %d bytes", len(audio_bytes))

            transcription = transcribe(audio_bytes, filename, openai_client)
            logger.info("文字起こし完了: %d 文字", len(transcription))

            save_transcription(
                notion=notion,
                database_id=NOTION_TRANSCRIPTION_DB_ID,
                filename=filename,
                transcription=transcription,
                gdrive_file_id=file_id,
                recorded_at=recorded_at,
            )

            move_to_processed(drive, file_id, GDRIVE_FOLDER_ID, processed_folder_id)
            logger.info("処理済みフォルダに移動: %s", filename)
            success += 1

        except Exception as e:
            logger.error("エラー（%s）: %s", filename, e)

    logger.info("=== 完了: %d / %d 件 ===", success, len(audio_files))


if __name__ == "__main__":
    main()
