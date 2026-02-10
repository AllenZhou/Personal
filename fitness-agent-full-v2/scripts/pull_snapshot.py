import argparse
from scripts.lib.notion_client import NotionClient
from scripts.lib.helpers import load_json, save_json

def _resolve_first_ds(nc: NotionClient, database_id: str) -> str:
    db = nc.retrieve_database(database_id)
    dss = db.get("data_sources", []) or []
    if not dss:
        raise RuntimeError(f"No data_sources for database_id={database_id}")
    return dss[0]["id"]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="snapshots/latest")
    ap.add_argument("--lookback", type=int, default=2)
    args = ap.parse_args()

    ids = load_json("config/notion_ids.json")
    mapping = load_json("config/notion_mapping.json")
    nc = NotionClient.from_env()

    try:
        ds_cache = load_json("config/notion_data_sources.json")
    except Exception:
        ds_cache = {}

    profile_ds = ds_cache.get("profileDynamic", {}).get("data_source_id") or _resolve_first_ds(nc, ids["profileDynamicDb"])
    session_ds = ds_cache.get("planSession", {}).get("data_source_id") or _resolve_first_ds(nc, ids["planSessionDb"])
    exercise_ds = ds_cache.get("planExercise", {}).get("data_source_id") or _resolve_first_ds(nc, ids["planExerciseDb"])
    feedback_ds = ds_cache.get("feedback", {}).get("data_source_id") or _resolve_first_ds(nc, ids["feedbackDb"])

    date_prop = mapping["profile_dynamic"]["properties"]["date"]
    prof = nc.data_source_query(profile_ds, {"page_size": 1, "sorts": [{"property": date_prop, "direction": "descending"}]})
    profile_latest = prof.get("results", [])

    sess_date_prop = mapping["plan_session"]["properties"]["target_date"]
    sessions = nc.data_source_query(session_ds, {"page_size": args.lookback, "sorts": [{"property": sess_date_prop, "direction": "descending"}]}).get("results", [])

    ex_rel_prop = mapping["plan_exercise"]["properties"]["session_rel"]
    fb_sess_rel_prop = mapping["feedback"]["properties"]["session_rel"]

    exercises = []
    feedback = []
    for s in sessions:
        sid = s["id"]
        exercises.extend(nc.data_source_query(exercise_ds, {"page_size": 100, "filter": {"property": ex_rel_prop, "relation": {"contains": sid}}}).get("results", []))
        feedback.extend(nc.data_source_query(feedback_ds, {"page_size": 100, "filter": {"property": fb_sess_rel_prop, "relation": {"contains": sid}}}).get("results", []))

    save_json(f"{args.outdir}/profile_dynamic_latest.json", profile_latest[0] if profile_latest else {})
    save_json(f"{args.outdir}/plan_sessions.json", sessions)
    save_json(f"{args.outdir}/plan_exercises.json", exercises)
    save_json(f"{args.outdir}/feedback.json", feedback)

    print("OK: snapshot pulled into", args.outdir)

if __name__ == "__main__":
    main()
