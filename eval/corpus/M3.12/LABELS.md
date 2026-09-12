# M3.12 — Change management

Labels fixed at authoring time, before any assessor run. Filenames are opaque on purpose:
scan_documents() prepends the filename to the chunk text, so a name containing the label
would be read by the assessor.

**Do not reuse these documents as few-shot prompt examples.**

---

## Boundary for this control

**Defined in `requirements/mas.yaml` under `controls.M3.12`, not here.** That file is what
the assessor is judged against and what a reviewer reads. Restating it here created two
definitions of `full` for one control and they diverged. Reproduced below for reading
convenience only; if the two disagree, the requirement file wins and these labels must be
re-argued.

**Requirement.** Changes to deployed AI models — including retraining, feature pipeline changes, threshold adjustments and decommissioning — are authorised before implementation, and the change that reached production is verifiably the change that was approved.

**Elements (6) — every applicable one must be evidenced for `full`:**

- `e0` — The change register is complete and internally consistent — no duplicate change ids, no unexplained gaps in the sequence, and entries current with the changes actually made
- `e1` — Model changes are raised as changes, including scheduled retraining
- `e2` — Authorisation is recorded before the first production action, including for emergency changes, evidenced by an approval timestamp and a production-action timestamp comparable to the minute
- `e3` — Privileged access used to implement the change is obtained against the approved change number, with no use of standing accounts *(applies only where privileged access management is in place)*
- `e3b` — The person who used that access is a named implementer on the approved change *(applies only where privileged access management is in place)*
- `e4` — Production state after implementation is verified against the approved plan, with deviations approved rather than closed silently *(applies only where a post-implementation verification step exists)*

| Rating | Condition (from the requirement file) |
|---|---|
| full | All applicable model-scoped elements evidenced across a tested population. An element whose applies_when condition is not met is recorded as not applicable with the reason, and does not count against the rating — a control managed adequately by other means is not a gap. Observations or housekeeping findings recorded in an assurance review do not prevent full |
| partial | Change records exist and cover the AI estate, but one or more of e0, e2, e3, e3b or e4 does not operate consistently across the tested population |
| none | A procedure, target operating model or intent, with no change records |

Maturity is judged separately and is not the label under test here.

---
## Cases

**Generated from `elements.yaml`. Do not edit by hand.** The label is derived, not
stated: all applicable elements evidenced = full, some = partial, none = none. Writing a
label here independently is how `M3.6_a` carried `full` for a week while failing three
elements — the model that rated it `partial` was right and the label was wrong.

Filenames are opaque on purpose: scan_documents() prepends the filename to the chunk
text, so a name containing the label would be read by the assessor.

### `M3.12_a.md` → **full**

5 evidenced, 0 not evidenced.

| element | | why |
|---|---|---|
| `e1` | Y | _a and _b section 'Retraining treated as change' |
| `e2` | Y | _a 'Approval before implementation', all 41 approved ahead of window; _b 2 of 7 emergency raised retrospectively |
| `e3` | Y | _a 'Privileged access', checkout raised against the corresponding change number, no standing access; _b F-03, 7 instances |
| `e3b` | Y | _a 'the checkout requester matched a named implementer on the approved change' |
| `e4` | Y | _a 'Implemented vs planned', 12 compared, all matched; _b 3 of 10 differ with no amendment |

---

### `M3.12_b.md` → **partial**

1 evidenced, 4 not evidenced.

| element | | why |
|---|---|---|
| `e1` | Y | _a and _b section 'Retraining treated as change' |
| `e2` | N | _a 'Approval before implementation', all 41 approved ahead of window; _b 2 of 7 emergency raised retrospectively |
| `e3` | N | _a 'Privileged access', checkout raised against the corresponding change number, no standing access; _b F-03, 7 instances |
| `e3b` | N | _a 'the checkout requester matched a named implementer on the approved change' |
| `e4` | N | _a 'Implemented vs planned', 12 compared, all matched; _b 3 of 10 differ with no amendment |

---

### `M3.12_c.md` → **none**

0 evidenced, 5 not evidenced.

| element | | why |
|---|---|---|
| `e1` | N | _a and _b section 'Retraining treated as change' |
| `e2` | N | _a 'Approval before implementation', all 41 approved ahead of window; _b 2 of 7 emergency raised retrospectively |
| `e3` | N | _a 'Privileged access', checkout raised against the corresponding change number, no standing access; _b F-03, 7 instances |
| `e3b` | N | _a 'the checkout requester matched a named implementer on the approved change' |
| `e4` | N | _a 'Implemented vs planned', 12 compared, all matched; _b 3 of 10 differ with no amendment |

---
