# Skill Diagnosis Manual Run

- run_id: `run-20260207-full`
- input digest: `/Users/allenzhou/MIRISE/agents/conversation-insights/output/skill_jobs/run-20260207-full/session_digests.json`
- output template: `/Users/allenzhou/MIRISE/agents/conversation-insights/output/skill_jobs/run-20260207-full/session_mechanism_template.json`

## Steps

1. Read digest and analyze each session using skill prompts.
2. Follow `/Users/allenzhou/MIRISE/agents/conversation-insights/skills/diagnose-session.md` to fill `sessions[]`.
3. Save completed JSON and apply it:
   `python3 scripts/pipeline.py diagnose apply --run-id run-20260207-full --result-file /Users/allenzhou/MIRISE/agents/conversation-insights/output/skill_jobs/run-20260207-full/session_mechanism_template.json`
4. Generate weekly mechanism:
   follow `/Users/allenzhou/MIRISE/agents/conversation-insights/skills/diagnose-weekly.md` or run `pipeline diagnose weekly --latest`.