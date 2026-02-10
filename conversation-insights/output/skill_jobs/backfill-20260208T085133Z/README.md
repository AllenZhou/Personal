# Diagnose Run

- run_id: `backfill-20260208T085133Z`
- sessions: `517`

## Next Steps

1. `python3 scripts/diagnose_helper.py run --engine manual --run-id backfill-20260208T085133Z`
2. Fill session mechanism outputs using the diagnose-session skill.
3. Apply results:
   `python3 scripts/diagnose_helper.py apply --run-id backfill-20260208T085133Z --result-file <result.json>`
4. Build incremental mechanism:
   `python3 scripts/diagnose_helper.py incremental --latest --sync-report`