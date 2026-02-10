from scripts.lib.notion_client import NotionClient

def _rt(text: str):
    return {"rich_text": [{"text": {"content": text}}]}

def build_plan_session_props(mapping: dict, plan: dict, session_key: str) -> dict:
    pmap = mapping["plan_session"]["properties"]
    sess = plan["session"]
    props = {
        pmap["target_date"]: {"date": {"start": sess["date"]}},
        pmap["type"]: {"select": {"name": sess["type"]}},
        pmap["status"]: {"select": {"name": "Ready"}},
        pmap["mode"]: {"select": {"name": sess["mode"]}},
        pmap["rationale"]: _rt(sess["rationale"]),
    }
    if "session_key" in pmap and pmap["session_key"]:
        props[pmap["session_key"]] = _rt(session_key)
    return props

def build_plan_exercise_props(mapping: dict, session_page_id: str, ex: dict) -> dict:
    pmap = mapping["plan_exercise"]["properties"]
    props = {
        pmap["session_rel"]: {"relation": [{"id": session_page_id}]},
        pmap["order"]: {"number": ex["order"]},
        pmap["name"]: _rt(ex["name"]),
        pmap["pattern"]: {"select": {"name": ex["pattern"]}},
        pmap["sets"]: {"number": ex["sets"]},
        pmap["reps_or_time"]: _rt(ex["reps_or_time"]),
        pmap["intensity"]: _rt(ex["intensity"]),
        pmap["risk_tags"]: {"multi_select": [{"name": t} for t in (ex.get("risk_tags") or [])]},
        pmap["variant_tag"]: _rt(ex.get("variant_tag", "")),
        pmap["notes"]: _rt(ex.get("notes", "")),
    }
    if pmap.get("rest_sec") and ex.get("rest_sec") is not None:
        props[pmap["rest_sec"]] = {"number": int(ex["rest_sec"])}
    if pmap.get("equipment"):
        props[pmap["equipment"]] = {"multi_select": [{"name": e} for e in (ex.get("equipment") or [])]}
    return props

def find_existing_session_by_key(nc: NotionClient, session_ds_id: str, mapping: dict, session_key: str):
    key_prop = mapping["plan_session"]["properties"].get("session_key")
    if not key_prop:
        return None
    data = nc.data_source_query(session_ds_id, {
        "page_size": 1,
        "filter": {"property": key_prop, "rich_text": {"equals": session_key}}
    })
    res = data.get("results", [])
    return res[0] if res else None
