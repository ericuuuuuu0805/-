#!/usr/bin/env python3
"""
Google Drive OAuth2 トークン初回取得スクリプト（一度だけ手元で実行する）。
取得した gdrive_token.json を GitHub Secrets に登録してください。

使い方:
  1. Google Cloud Console で Google Drive API を有効化
     （Gmail と同じプロジェクト・同じ credentials.json で OK）
  2. credentials.json をこのスクリプトと同じディレクトリに置く
  3. python scripts/setup_gdrive_token.py を実行
  4. ブラウザで Google アカウントを認可
  5. 出力された JSON を GitHub Secret「GDRIVE_TOKEN_JSON」に登録
  6. 録音ファイルを置く Google Drive フォルダの ID を
     GitHub Secret「GDRIVE_AUDIO_FOLDER_ID」に登録
"""

from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

SCOPES = ["https://www.googleapis.com/auth/drive"]
CREDS_FILE = Path("credentials.json")
TOKEN_FILE = Path("gdrive_token.json")


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
        print("\n✅ gdrive_token.json を保存しました")

    print("\n--- GitHub Secret に登録する内容 ---")
    print("\n[GDRIVE_TOKEN_JSON]")
    print(TOKEN_FILE.read_text())


if __name__ == "__main__":
    main()
