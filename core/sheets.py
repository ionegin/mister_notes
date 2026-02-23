import json
import logging
import gspread
from google.oauth2.service_account import Credentials
from config import GOOGLE_CREDENTIALS, SPREADSHEET_ID

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

def _get_sheet():
    creds_dict = json.loads(GOOGLE_CREDENTIALS)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID).sheet1

def add_user(user_id: int):
    try:
        sheet = _get_sheet()
        existing = sheet.col_values(1)
        if str(user_id) not in existing:
            sheet.append_row([user_id])
    except Exception as e:
        logging.error(f"Sheets add_user error: {e}")

def get_all_users() -> list[int]:
    try:
        sheet = _get_sheet()
        values = sheet.col_values(1)
        return [int(v) for v in values if v.isdigit()]
    except Exception as e:
        logging.error(f"Sheets get_all_users error: {e}")
        return []