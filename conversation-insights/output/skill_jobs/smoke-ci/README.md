# Diagnose Run

- run_id: `smoke-ci`
- sessions: `1`

## Next Steps

1. `python3 scripts/pipeline.py diagnose run --engine manual --run-id smoke-ci`
2. Fill session mechanism outputs using the diagnose-session skill.
3. Apply results:
   `python3 scripts/pipeline.py diagnose apply --run-id smoke-ci --result-file <result.json>`
4. Build weekly mechanism:
   `python3 scripts/pipeline.py diagnose weekly --latest --sync-report`