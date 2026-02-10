# Diagnose Run

- run_id: `backfill-20260207T192956Z`
- sessions: `608`

## Next Steps

1. `python3 scripts/diagnose_helper.py run --engine manual --run-id backfill-20260207T192956Z`
2. Fill session mechanism outputs using the diagnose-session skill.
3. Apply results:
   `python3 scripts/diagnose_helper.py apply --run-id backfill-20260207T192956Z --result-file <result.json>`
4. Build incremental mechanism:
   `python3 scripts/diagnose_helper.py incremental --latest --sync-report`