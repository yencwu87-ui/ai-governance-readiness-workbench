# Match threshold

*Section for the user guide. Describes behaviour as of WB-023.*

## What it does

When you scan a folder, the workbench splits every document into passages and ranks them
against each control using BM25 keyword scoring. The match threshold decides how many of
those ranked passages are kept as evidence for that control.

It is a **relative** threshold. A passage is kept if it scores at least this fraction of
the best-scoring passage for that same control. At the default of 0.35, a passage must
score at least 35% of the best match to be included. Up to three passages are kept per
control.

Relative, not absolute, for a reason. BM25 scores are unbounded and depend on how many
words the control is written with — a 47-word MAS control and an 8-word NIST subcategory
produce scores on completely different scales, so no single absolute number means the same
thing across libraries. A percentage of the best match does.

## What moving it does

**Lower (0.0–0.25)** keeps weaker matches. More controls receive evidence, and more of
that evidence is only loosely related. The assessor will be reading passages that mention
a keyword from the control without addressing it. Expect more proposals to come back
`none` with gaps that describe the control rather than the organisation.

**Default (0.35)** keeps passages that are in the same territory as the best match.

**Higher (0.5–1.0)** keeps only passages close to the best match, often just one. Evidence
is tighter, but controls whose evidence is spread across several documents may lose the
supporting passages and be assessed on one. At 1.0 only exact ties with the best match
survive.

## The distinction that matters

After a scan, the workbench reports how many in-scope controls had candidate evidence
found. **A control with no matching document is not the same finding as a control whose
evidence was excluded by the threshold.** The first means nothing in the folder relates to
the control. The second means something did, but not closely enough at the setting you
used.

The scan summary shows the threshold it was run at for this reason. If a control you
expected to be evidenced shows nothing, lower the threshold and re-check before recording
that finding.

## It is recorded

Every assessment stores the threshold it was made under, alongside the passages it read
and the model that read them. This matters because two reviewers scanning the same folder
at different settings will see different evidence and may reach different ratings — both
legitimately. Without the setting on the record, neither proposal can be reproduced or
challenged later.

## What it does not do

The threshold selects evidence. It does not influence the rating: the assessor sees the
passages that survived and nothing about the threshold that selected them, and the
validation harness can only lower a rating, never raise it. Lowering the threshold to
"find more evidence" will not produce a better rating — it will produce more passages for
the assessor to find nothing in.

## Note on history

Before WB-023 this control was labelled on a 1–10 absolute scale defaulting to 4.0, and
was wired to `min_score`, an absolute BM25 floor. On a 195-control run the weakest
control's top score was 16.6, so a floor of 4 excluded almost nothing and the slider had
little effect on what was retrieved. Assessments made before WB-023 were effectively all
made at the default relative gate regardless of where the slider sat, and do not carry
their retrieval settings on the record.
