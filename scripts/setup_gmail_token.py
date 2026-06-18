#!/usr/bin/env python3
"""
Gmail OAuth2 トークン初回取得スクリプト（一度だけ手元で実行する）。
取得した token.json を GitHub Secrets に登録してください。

使い方:
  1. Google Cloud Console で Gmail API を有効化し、
     OAuth2 クライアント ID（デスクトップアプリ）を作成
  2. credentials.json をこのスクリプトと同じディレクトリに置く
  3. python setup_gmail_token.py を実行
  4. ブラウザで認可 → token.json が生成される
  5. cat token.json の内容を GitHub Secret「GMAIL_TOKEN_JSON」に登録
  6. cat credentials.json の内容を GitHub Secret「GMAIL_CREDENTIALS_JSON」に登録
"""

import json
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CREDS_FILE = Path("credentials.json")
TOKEN_FILE = Path("token.json")


def main():
    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)

        TOKEN_FILE.write_text(creds.to_json())
        print(f"\n✅ token.json を保存しました")

    print("\n--- GitHub Secret に登録する内容 ---")
    print("\n[GMAIL_TOKEN_JSON]")
    print(TOKEN_FILE.read_text())
    print("\n[GMAIL_CREDENTIALS_JSON]")
    print(CREDS_FILE.read_text())


if __name__ == "__main__":
    main()
