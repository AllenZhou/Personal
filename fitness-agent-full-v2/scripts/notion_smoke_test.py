# Minimal Notion read/write smoke test (API 2025-09-03, data sources)
import json, os, sys
from datetime import datetime, timezone
from dotenv import load_dotenv

from scripts.lib.notion_client import NotionClient

def die(msg):
    print(f"[ERROR] {msg}", file=sys.stderr)
    sys.exit(1)

def main():
    load_dotenv()
    token = os.getenv("NOTION_TOKEN")
    if not token:
        die("Missing NOTION_TOKEN in .env")

    with open("config/notion_ids.json","r",encoding="utf-8") as f:
        ids = json.load(f)

    with open("config/notion_mapping.json","r",encoding="utf-8") as f:
        mapping = json.load(f)

    nc = NotionClient(token)

    def ds_id(db_id: str) -> str:
        db = nc.retrieve_database(db_id)
        dss = db.get("data_sources", []) or []
        if not dss:
            die(f"No data_sources for database_id={db_id}")
        return dss[0]["id"]

    profile_ds = ds_id(ids["profileDynamicDb"])
    plan_session_ds = ds_id(ids["planSessionDb"])

    date_prop = mapping["profile_dynamic"]["properties"]["date"]
    data = nc.data_source_query(profile_ds, {
        "page_size": 1,
        "sorts": [{"property": date_prop, "direction": "descending"}],
    })
    rows = data.get("results", [])
    if not rows:
        die("Profile Dynamic is empty (add at least 1 row)")
    print("Profile Dynamic OK")

    today = datetime.now(timezone.utc).date().isoformat()
    ps = mapping["plan_session"]["properties"]
    payload = {
        "parent": {"type": "data_source_id", "data_source_id": plan_session_ds},
        "properties": {
            ps["target_date"]: {"date": {"start": today}},
            ps["type"]: {"select": {"name": "A"}},
            ps["status"]: {"select": {"name": "NeedsPlan"}},
            ps["mode"]: {"select": {"name": "Normal"}},
            ps["rationale"]: {"rich_text": [{"text": {"content": "integration test"}}]},
        },
    }
    nc.create_page(payload)
    print("Plan Session create OK")

if __name__ == "__main__":
    main()
