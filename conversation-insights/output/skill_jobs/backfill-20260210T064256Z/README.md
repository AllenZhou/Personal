# Diagnose Run

- run_id: `backfill-20260210T064256Z`
- sessions: `784`

## Next Steps

1. `python3 scripts/diagnose_helper.py run --engine manual --run-id backfill-20260210T064256Z`
2. Fill session mechanism outputs using the diagnose-session skill.
3. Apply results:
   `python3 scripts/diagnose_helper.py apply --run-id backfill-20260210T064256Z --result-file <result.json>`
4. Build incremental mechanism (Skill output required):
   `python3 scripts/diagnose_helper.py incremental --run-id backfill-20260210T064256Z --result-file <incremental_result.json> --sync-report`