# Fitness Agent (Full Skeleton)

This project is a **local, Notion-SSOT fitness planning agent** intended for development in **Cursor**.

## What this repo does (MVP)
- Pulls latest state from Notion (Profile Dynamic + recent Sessions/Exercises/Feedback)
- Loads policy from `.claude/skills/policy.training_plan.md` (structured YAML)
- Generates the **next single session** (A/B/C/D), **no exercise library DB**
- Validates output (schema + hard rules + stability budget M)
- Pushes session + exercises back to Notion idempotently

## Quickstart (after you add NOTION_TOKEN)
1) Create `.env` from `.env.example` and set `NOTION_TOKEN=...`
2) Install deps:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3) (Recommended) Cache data source ids (Notion API 2025-09-03):
   ```bash
   python scripts/resolve_data_sources.py
   ```

4) Verify Notion connectivity:
   ```bash
   python scripts/notion_smoke_test.py
   ```
5) Run the orchestrator:
   ```bash
   python scripts/run_next.py --type A --date 2026-01-26
   ```

## Configuration
- `config/notion_ids.json`: database/page IDs
- `config/notion_mapping.json`: **property names** and select option names (must match Notion exactly)
- `config/settings.json`: general settings (lookback window, etc.)

## Important
- This repo intentionally **does not include a pre-defined exercise library database**.
- The generator uses **pattern recipes + constraints** to create stable sessions; you can refine the generator logic later.
