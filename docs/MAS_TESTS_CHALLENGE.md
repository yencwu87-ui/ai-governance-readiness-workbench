# Second challenge — against v3

The first challenge is largely consumed: v2 fixed M3.11's vagueness, F3's missing
non-delegable clause, M3.15's hinge, F1's §D route, M2.2's resource crosswalk, the FEAT feed
at M1.2, and the ignored play links. v3 then added the CSA PA column I had skipped.

So the useful question is not what v1 got wrong. It is **what v3 got wrong, and whether it is
more confident than its evidence supports.** It is.

---

## 1. The confidence problem is the main finding

v3 carries 13 parallel-read entries. **Twelve are `SHAPE`.** One is `KNOWN`. The instruments I
lean on hardest — the CII regime, outsourcing requirements, Notice 655, BCM — are all ones I
told you I know only in shape.

The writing does not reflect that. "Confirm the process determines whether the arrangement is
outsourcing, and if so whether it is material outsourcing, and routes it to the existing
register" reads like someone who has the outsourcing guidelines open. I do not. I know the
regime has a register and a materiality concept; I do not know the classification thresholds,
the notification triggers, or whether a foundation-model API subscription is even in scope.

**That last point matters and I glossed it.** I asserted a foundation-model provider serving
customer-affecting decisions is "a candidate material outsourcing arrangement." Whether a
consumption-priced API with no data processing agreement constitutes outsourcing at all is a
live question that firms answer differently. I stated a conclusion where the honest output was
a question.

The same applies to M3.11's CII path, which is the highest-consequence item in the file. I do
not know whether the Commissioner's notification clock is shorter or longer than MAS's, what
the trigger threshold is, or whether an AI system supporting a CII inherits the designation.
Every one of those changes the test.

**What to do.** Do not treat any `SHAPE` entry as drafted. Treat it as a question to take to
the instrument: *does this obligation exist, on what trigger, to whom, by when.* The value of
v3 is that it tells you where to look, not what you will find.

## 2. "Cite the existing evidence rather than re-testing" may cause under-testing

Eleven parallel entries are `same-population`, and several tell you to cite the existing TRMG
or 655 evidence instead of re-performing the test. That advice is only safe if the existing
test's population actually included the AI estate.

It very often does not. A TRMG change-and-access test scoped to core banking, payments and
customer channels may never have touched the model-serving platform — which may not have
existed when the scope was set, may sit in a different environment, and may be operated by a
data science function outside the change regime the test covers.

So the advice is inverted. Before citing existing evidence, the test must first confirm the
existing test's scope **included** the AI estate. If it did not, there is no evidence to cite
and the AI test is not a duplicate at all — it is the only test.

I would rewrite every `same-population` entry to lead with that scope check. As written, v3
gives a plausible route to concluding a control is evidenced when nobody has tested it.

## 3. Test length went up and executability went down

M3.11's design test now carries three separate obligations — the FSM-N05 clocks, the CII
routing determination, and PA 10's automated response. Its operating test has three
populations. That is one test doing the work of three, and a test that large gets partially
performed and fully signed off.

The same happened to M3.7 and M3.14. v1's tests were too thin; v3's are too dense. The
correction is to split by obligation, not to trim words — M3.11 should be three tests with
three dispositions, because a firm can pass the MAS clock and fail the CII one and the record
needs to say so.

## 4. What I did verify, and it holds

The CSA PA references are correct. I checked all 30 against the sheet's own Linked CSA PA
column and against the crosswalk sheet read in the other direction: **30 of 30 match, and the
two sources agree with each other.** Eleven controls have no PA reference in the sheet
(M3.1–M3.5, M3.8, M3.9, F1–F4) and I added none, which is right.

That is the only claim in v3 I can demonstrate rather than assert. Worth noting the contrast:
the thing I could check is fine, and the things I could not check are the ones carrying the
weight.

## 5. Items from challenge 1 that are still open

- **Sample sizes.** Still absent everywhere. "Sample changes" is not reproducible.
- **Cadences.** Partly fixed — M1.1 now says "per the control's review cycle" — but M3.12
  still says "one quarter" and others say "for the period" with no basis.
- **Design versus operating for M4.1 and M4.2.** v3 labels the split in a header comment but
  the fields are still called design and operating, which overstates what they establish. They
  are plan-versus-actual.
- **Disposition.** Still no statement of what a failure means. Flagged as deliberately open,
  and it should be closed before these are used, because M3.11 now has three populations that
  could fail independently.

## 6. New: the MindForge caution may be understated

Three controls cite the MindForge AI Risk Management Toolkit (Mar 2026) and carry a
`source_caution`. But M3.15 is the agentic hinge routing into two entire control libraries,
and M3.10 covers all post-deployment monitoring. If the toolkit specifies monitoring metrics or
GenAI risk categories, the caution is not a footnote — those two tests may be substantially
wrong rather than merely incomplete.

---

## What I would fix, in order

1. **Rewrite the `same-population` entries to lead with a scope check.** This is the one that
   can cause a control to be recorded as evidenced when it was never tested.
2. **Downgrade the `SHAPE` prose to questions.** M3.14's outsourcing paragraph and M3.11's CII
   paragraph should read as things to establish, not things established.
3. **Split M3.11 into three tests** with separate dispositions.
4. Sample sizes and cadences, which are formatting.

And the honest summary: v3 is a better map of where to look than v1 was, and it is not yet a
set of tests anyone should run against a client. The gap between how it reads and what stands
behind it is the finding.
