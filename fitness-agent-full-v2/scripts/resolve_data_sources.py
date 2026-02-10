import argparse
from scripts.lib.notion_client import NotionClient
from scripts.lib.helpers import load_json, save_json

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="config/notion_data_sources.json")
    args = ap.parse_args()

    ids = load_json("config/notion_ids.json")
    nc = NotionClient.from_env()

    out = {}
    for key, db_id in [
        ("profileDynamic", ids["profileDynamicDb"]),
        ("planSession", ids["planSessionDb"]),
        ("planExercise", ids["planExerciseDb"]),
        ("feedback", ids["feedbackDb"]),
    ]:
        db = nc.retrieve_database(db_id)
        dss = db.get("data_sources", []) or []
        if not dss:
            raise RuntimeError(f"No data_sources found for database {key} ({db_id}).")
        out[key] = {"database_id": db_id, "data_source_id": dss[0]["id"], "data_source_name": dss[0].get("name","")}
    save_json(args.out, out)
    print("OK: wrote", args.out)

if __name__ == "__main__":
    main()
