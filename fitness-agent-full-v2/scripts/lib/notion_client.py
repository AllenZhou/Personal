import os, requests
from dotenv import load_dotenv

# Notion introduced multi-source databases in API version 2025-09-03.
# Using older Notion-Version will fail for databases that have multiple data sources.
NOTION_VERSION = "2025-09-03"
API = "https://api.notion.com/v1"

class NotionClient:
    def __init__(self, token: str):
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    @staticmethod
    def from_env():
        load_dotenv()
        token = os.getenv("NOTION_TOKEN")
        if not token:
            raise RuntimeError("Missing NOTION_TOKEN in .env")
        return NotionClient(token)

    # --- Database container ---
    def retrieve_database(self, database_id: str):
        url = f"{API}/databases/{database_id}"
        r = requests.get(url, headers=self.headers, timeout=30)
        r.raise_for_status()
        return r.json()

    # --- Data sources (new) ---
    def data_source_query(self, data_source_id: str, payload: dict):
        url = f"{API}/data_sources/{data_source_id}/query"
        r = requests.post(url, headers=self.headers, json=payload, timeout=30)
        r.raise_for_status()
        return r.json()

    # --- Pages ---
    def retrieve_page(self, page_id: str):
        url = f"{API}/pages/{page_id}"
        r = requests.get(url, headers=self.headers, timeout=30)
        r.raise_for_status()
        return r.json()

    def retrieve_block_children(self, block_id: str, page_size: int = 100):
        url = f"{API}/blocks/{block_id}/children?page_size={page_size}"
        r = requests.get(url, headers=self.headers, timeout=30)
        r.raise_for_status()
        return r.json()

    def create_page(self, payload: dict):
        url = f"{API}/pages"
        r = requests.post(url, headers=self.headers, json=payload, timeout=30)
        r.raise_for_status()
        return r.json()

    def update_page(self, page_id: str, payload: dict):
        url = f"{API}/pages/{page_id}"
        r = requests.patch(url, headers=self.headers, json=payload, timeout=30)
        r.raise_for_status()
        return r.json()
