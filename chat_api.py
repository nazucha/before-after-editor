"""Google Chat API クライアント（OAuth2 ユーザー認証 + スレッド返信対応）"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/chat.messages",
    "https://www.googleapis.com/auth/chat.messages.readonly",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]
JST = timezone(timedelta(hours=9))

BASE_DIR = Path(__file__).parent
OAUTH_CREDS_PATH = BASE_DIR / "oauth_credentials.json"
TOKEN_PATH = BASE_DIR / "token.json"


def get_credentials():
    """OAuth2 認証済みのクレデンシャルを取得する"""
    creds = None

    # 保存済みトークンがあれば読み込む
    token_json = os.environ.get("GOOGLE_CHAT_TOKEN")
    if token_json:
        creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
    elif TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    # スコープが不足している場合は再認証
    if creds and creds.valid and not set(SCOPES).issubset(set(creds.scopes or [])):
        creds = None

    # トークンがないか期限切れなら認証フロー実行
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(OAUTH_CREDS_PATH), SCOPES
            )
            creds = flow.run_local_server(port=0)

        # トークンを保存
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    return creds


def build_chat_service():
    """OAuth2 認証済みの Chat API サービスを構築する"""
    return build("chat", "v1", credentials=get_credentials())


def build_drive_service():
    """OAuth2 認証済みの Drive API サービスを構築する"""
    return build("drive", "v3", credentials=get_credentials())


def build_sheets_service():
    """OAuth2 認証済みの Sheets API サービスを構築する"""
    return build("sheets", "v4", credentials=get_credentials())


def _normalize_fullwidth(text):
    """全角数字・スラッシュを半角に変換する"""
    table = str.maketrans("０１２３４５６７８９／", "0123456789/")
    return text.translate(table)


def find_daily_report_thread(service, space_id, target_date=None):
    """今日の日報スレッド（最初の投稿）を見つけてthread nameを返す

    当日の日付（例: 3/23）を含むメッセージを検索する。
    全角数字・全角スラッシュにも対応。
    """
    if target_date is None:
        target_date = datetime.now(JST).date()

    # 検索パターン: "3/23" のような日付文字列
    date_pattern = f"{target_date.month}/{target_date.day}"

    # JST の当日0時 = UTC の前日15時
    start_utc = datetime(
        target_date.year, target_date.month, target_date.day,
        tzinfo=JST
    ).astimezone(timezone.utc)

    filter_str = f'createTime > "{start_utc.strftime("%Y-%m-%dT%H:%M:%SZ")}"'

    response = service.spaces().messages().list(
        parent=f"spaces/{space_id}",
        filter=filter_str,
        pageSize=100,
    ).execute()

    messages = response.get("messages", [])

    for msg in messages:
        text = msg.get("text", "")
        normalized = _normalize_fullwidth(text)
        if date_pattern in normalized:
            return msg["thread"]["name"]

    return None


def reply_to_thread(service, space_id, thread_name, message_text):
    """既存スレッドに返信する"""
    return service.spaces().messages().create(
        parent=f"spaces/{space_id}",
        body={
            "text": message_text,
            "thread": {"name": thread_name},
        },
        messageReplyOption="REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD",
    ).execute()


def send_new_message(service, space_id, message_text):
    """新規メッセージとして送信する（スレッドが見つからない場合のフォールバック）"""
    return service.spaces().messages().create(
        parent=f"spaces/{space_id}",
        body={"text": message_text},
    ).execute()
