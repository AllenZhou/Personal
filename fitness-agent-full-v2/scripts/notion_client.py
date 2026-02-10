import requests, os
from dotenv import load_dotenv

load_dotenv()
NOTION_VERSION = "2022-06-28"
API = "https://api.notion.com/v1"

def headers():
    return {
        "Authorization": f"Bearer {os.getenv('NOTION_TOKEN')}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
