#!/usr/bin/env python3
"""
Initial setup: Run this ONCE on your local machine to generate Gmail OAuth tokens.
Copy the output JSON strings to GitHub Secrets.

Usage:
  pip install google-auth-oauthlib google-api-python-client
  python scripts/setup_gmail_auth.py --credentials /path/to/credentials.json
"""

import argparse
import json
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def main():
    parser = argparse.ArgumentParser(description="Generate Gmail OAuth tokens for GitHub Actions")
    parser.add_argument("--credentials", required=True, help="Path to Google OAuth credentials.json")
    args = parser.parse_args()

    with open(args.credentials) as f:
        credentials_data = json.load(f)

    flow = InstalledAppFlow.from_client_secrets_file(args.credentials, SCOPES)
    creds = flow.run_local_server(port=0)

    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes),
    }

    print("\n" + "=" * 60)
    print("以下の値をGitHub Secretsに設定してください:")
    print("=" * 60)
    print("\n[GMAIL_CREDENTIALS_JSON]")
    print(json.dumps(credentials_data))
    print("\n[GMAIL_TOKEN_JSON]")
    print(json.dumps(token_data))
    print("=" * 60)


if __name__ == "__main__":
    main()
