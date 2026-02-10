# Diagnose Run

- run_id: `codex-smoke-20260208`
- sessions: `1`

## Next Steps

1. `python3 scripts/diagnose_helper.py run --engine manual --run-id codex-smoke-20260208`
2. Fill session mechanism outputs using the diagnose-session skill.
3. Apply results:
   `python3 scripts/diagnose_helper.py apply --run-id codex-smoke-20260208 --result-file <result.json>`
4. Build incremental mechanism:
   `python3 scripts/diagnose_helper.py incremental --latest --sync-report`