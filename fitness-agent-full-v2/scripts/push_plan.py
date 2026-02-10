import argparse
from scripts.lib.notion_client import NotionClient
from scripts.lib.helpers import load_json
from scripts.lib.notion_props import build_plan_session_props, build_plan_exercise_props, find_existing_session_by_key

def _resolve_first_ds(nc: NotionClient, database_id: str) -> str:
    db = nc.retrieve_database(database_id)
    dss = db.get("data_sources", []) or []
    if not dss:
        raise RuntimeError(f"No data_sources for database_id={database_id}")
    return dss[0]["id"]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", default="outputs/next_session.json")
    args = ap.parse_args()

    ids = load_json("config/notion_ids.json")
    mapping = load_json("config/notion_mapping.json")
    plan = load_json(args.plan)

    nc = NotionClient.from_env()

    try:
        ds_cache = load_json("config/notion_data_sources.json")
    except Exception:
        ds_cache = {}

    session_ds = ds_cache.get("planSession", {}).get("data_source_id") or _resolve_first_ds(nc, ids["planSessionDb"])
    exercise_ds = ds_cache.get("planExercise", {}).get("data_source_id") or _resolve_first_ds(nc, ids["planExerciseDb"])

    session_key = plan["meta"]["session_key"]

    existing = find_existing_session_by_key(nc, session_ds, mapping, session_key)
    if existing:
        session_page_id = existing["id"]
    else:
        payload = {
            "parent": {"type": "data_source_id", "data_source_id": session_ds},
            "properties": build_plan_session_props(mapping, plan, session_key),
        }
        created = nc.create_page(payload)
        session_page_id = created["id"]

    for ex in plan["exercises"]:
        payload = {
            "parent": {"type": "data_source_id", "data_source_id": exercise_ds},
            "properties": build_plan_exercise_props(mapping, session_page_id, ex),
        }
        nc.create_page(payload)

    print("OK: pushed plan to Notion (session_page_id=%s)" % session_page_id)

if __name__ == "__main__":
    main()
