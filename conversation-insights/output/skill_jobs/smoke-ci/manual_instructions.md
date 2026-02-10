# Skill Diagnosis Manual Run

- run_id: `smoke-ci`
- input digest: `/Users/allenzhou/MIRISE/agents/conversation-insights/output/skill_jobs/smoke-ci/session_digests.json`
- output template: `/Users/allenzhou/MIRISE/agents/conversation-insights/output/skill_jobs/smoke-ci/session_mechanism_template.json`

## Steps

1. Read digest and analyze each session using skill prompts.
2. Follow `/Users/allenzhou/MIRISE/agents/conversation-insights/skills/diagnose-session.md` to fill `sessions[]`.
3. Save completed JSON and apply it:
   `python3 scripts/pipeline.py diagnose apply --run-id smoke-ci --result-file /Users/allenzhou/MIRISE/agents/conversation-insights/output/skill_jobs/smoke-ci/session_mechanism_template.json`
4. Generate weekly mechanism:
   follow `/Users/allenzhou/MIRISE/agents/conversation-insights/skills/diagnose-weekly.md` or run `pipeline diagnose weekly --latest`.