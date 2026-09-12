# MAS regulatory change runbook

The live requirement file is `requirements/mas.yaml`. A new regulatory publication must **not** overwrite it directly.

## 1. Capture the source

Record the authoritative publication, issue date, effective date, owner, and retrieval/hash information. Keep the source file locally where evidence policy permits.

## 2. Create a draft

```bash
PYTHONPATH=. python tools/draft_regulatory_change.py \
  --source-title "<publication title>" \
  --source-reference "<URL or document ID>" \
  --effective-from "YYYY-MM-DD" \
  --ticket "WB-031" \
  --out requirements/drafts/mas-YYYY-MM-DD-draft.yaml
```

This copies the current control set as the base and records the live-version SHA. The live file is untouched.

## 3. Edit only the draft

Change only affected controls in the draft:

- `requirement`
- `elements`
- `boundary`
- applicability/conditions
- requirement source/provenance

Then update the related Test of Design/Test of Operating Effectiveness procedures and the executable MAS test specification where the test logic changes.

## 4. Impact-map the change

The draft records changed/added/removed controls. Each affected control is required to undergo test review. The executable catalog maps the control to its ToD/ToE test IDs.

## 5. Shadow-test before activation

Run the current requirement/test set and the draft requirement/test set against the **same evidence population**. Compare:

- changed control conclusions
- newly failing tests
- newly not-testable tests
- changed boundaries
- affected evaluation cases
- reviewer workload / challenge implications

The draft remains non-authoritative throughout shadow testing.

## 6. Human approval

The control owner and Compliance/Governance reviewer approve the semantic change and test change under the change ticket. The approval record must identify the exact draft hash.

## 7. Promote as an immutable release

```python
from governance.regulatory_change import promote_draft
promote_draft(
    "requirements/drafts/mas-YYYY-MM-DD-draft.yaml",
    approved_by="<named approver>",
    change_ticket="WB-031",
)
```

Promotion writes a separate approved release under `requirements/releases/`. It does not overwrite `requirements/mas.yaml`.

The live pointer is switched only through the normal controlled deployment process.

## 8. Effective-date activation

Do not activate early merely because approval is complete. The deployment should carry the approved release hash and the regulatory effective date. Where the regulation has a future effective date, the engine can shadow-test ahead of time and activate on the approved effective date.

## 9. Post-effective monitoring

For the first review cycle after activation, monitor:

- controls whose requirement or boundary changed;
- test failures and NOT_TESTABLE results;
- AI assessor label shifts on impacted evaluation cases;
- Challenger patterns generated from the new interpretation;
- exceptions created because of implementation gaps.

This creates a closed loop:

`regulation → draft → impact → test → shadow → approval → release → monitoring`.
