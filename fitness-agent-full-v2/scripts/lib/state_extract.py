from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Set

def build_session_key(date_str: str, session_type: str, mode: str) -> str:
    return f"{date_str}:{session_type}:{mode}"

def _parse_notion_date(prop: dict) -> str:
    # Notion date property: {"date":{"start":"YYYY-MM-DD"...}}
    if not prop:
        return ""
    d = prop.get("date", {})
    return d.get("start", "") if isinstance(d, dict) else ""

def _get_select_name(prop: dict) -> str:
    if not prop:
        return ""
    sel = prop.get("select")
    return sel.get("name", "") if isinstance(sel, dict) else ""

def _get_checkbox(prop: dict) -> bool:
    if not prop:
        return False
    return bool(prop.get("checkbox", False))

def _get_rich_text(prop: dict) -> str:
    if not prop:
        return ""
    parts = prop.get("rich_text", []) or []
    out = []
    for p in parts:
        t = p.get("plain_text")
        if t:
            out.append(t)
    return "".join(out)

def extract_risk_signal(state: Dict[str, Any]) -> bool:
    # Look at recent feedback records
    fb = state.get("feedback", []) or []
    hard_count = 0
    for r in fb:
        props = r.get("properties", {})
        pain = _get_select_name(props.get("Pain"))
        next_day = _get_select_name(props.get("NextDay"))
        diff = _get_select_name(props.get("Difficulty"))
        if pain == "Significant" or next_day == "Bad":
            return True
        if diff == "Hard":
            hard_count += 1
    return hard_count >= 2

def compute_weekly_variant_count(state: Dict[str, Any], lookback_days: int = 7) -> int:
    # We approximate by scanning generated exercises stored in Notion snapshot and counting variant tags ending with :v1
    # Requires that Plan Exercise has VariantTag property (text or rich_text)
    now = datetime.now(timezone.utc).date()
    sessions = state.get("sessions", []) or []
    exercises = state.get("exercises", []) or []

    # Map session id -> date
    sess_date = {}
    for s in sessions:
        props = s.get("properties", {})
        d = props.get("Target_Date", {})  # default name; caller should align mapping in snapshot pull if needed
        date_str = _parse_notion_date(d)
        sess_date[s.get("id")] = date_str

    cutoff = now - timedelta(days=lookback_days)
    # Collect session ids in window
    sess_ids = set()
    for sid, ds in sess_date.items():
        if not ds:
            continue
        try:
            d = datetime.fromisoformat(ds).date()
        except Exception:
            continue
        if d >= cutoff:
            sess_ids.add(sid)

    count = 0
    for ex in exercises:
        props = ex.get("properties", {})
        # relation contains session ids
        rel = props.get("Session", {}).get("relation", []) or []
        belongs = any(item.get("id") in sess_ids for item in rel)
        if not belongs:
            continue
        # variant tag stored as text/rich_text
        vt = props.get("VariantTag")
        tag = _get_rich_text(vt) if vt and "rich_text" in vt else (vt.get("title",[{}])[0].get("plain_text","") if vt and "title" in vt else "")
        if ":v1" in tag:
            count += 1
    return count
