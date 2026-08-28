# Task 06b — the evening section buries its own result

Task 06 is accepted; the slim Parquet output and the previous-evening scoping are both right.
This is about what the brief says. Read `AGENTS.md`, then PLAN.md sections 8, 13.2 and **13.5**,
which is new.

---

## The problem

Here is what the 2026-08-23 brief actually renders:

```
Pixels flagged above threshold: 37 - 37 in daylight before sunset
(unreliable: reflected sunlight), 0 after dark.
- 15:00 WIT, -1.07704, 136.04656: B07 anomaly +11.6 K (in daylight ... unreliable)
- ... 19 more lines, every one of them labelled unreliable ...
- and 17 more (see the evening file)
That is not evidence that nothing burned: ...
```

Three things are wrong with this, and none of them is a factual error.

**1. The mandated sentence never appears.** Task 06 required "No evening thermal anomaly above
threshold." for a run with no flags. It was implemented as *no flags at all*. But the run that
matters is this one: zero after dark, some in daylight. The one number a reader needs — nothing
was seen after sunset — is rendered as a trailing clause, `0 after dark`, and the required
sentence is skipped entirely.

**2. The headline number counts pixels the brief itself calls unreliable.** "Pixels flagged above
threshold: 37" is the first and largest figure in the section, and all 37 are daylight readings
the next clause disowns. A reader skimming takes away 37.

**3. Twenty lines of disowned data crowd out the finding.** The daylight rows are enumerated in
full while the after-dark result gets a clause. The section spends its length on what it says
cannot be trusted.

This is not dishonest and every individual statement is true. It is the failure section 8 is
about: accurate parts assembled into a misleading emphasis.

## Required

**Lead with after dark.** The section's first fact is the after-dark result. When no pixel is
flagged after sunset, render exactly:

> No evening thermal anomaly above threshold after dark.

followed by the existing "That is not evidence that nothing burned" paragraph. This must appear
whenever the after-dark count is zero, **regardless of the daylight count**.

**Separate the two counts, and do not lead with the total.** Report after-dark flags and daylight
flags as distinct figures. Never print a single combined "pixels flagged" number as the headline.

**List after-dark flags in full; summarise daylight ones.** After-dark rows are the product and
there will rarely be many. Daylight rows collapse to one line — count, time range, peak anomaly —
with the file named for anyone who wants them. The 20-row cap can go; it exists only because
daylight rows were being enumerated.

## Also record the decay, carefully

PLAN.md 13.5 documents that the pixel 1.3 km from Frans Kaisiepo cooled monotonically from +5.58 K
at 18:30 WIT into the noise by 20:00, about 4.4 standard deviations above the night's land field
at its peak. That is the best evidence the project has that burning continues past sunset below
the detection floor.

Add to the evening section, when the after-dark count is zero, the **largest after-dark anomaly
and the time it occurred**, as a single line. Something a reader can weigh:

> Largest after-dark anomaly: +5.6 K at 18:30 WIT (-1.1857, 136.1186). Below the 10 K flag
> threshold and not a detection.

The last clause is mandatory. A sub-threshold number published without it becomes a detection the
moment someone quotes it.

Do not add the time series, the standard-deviation figure, or any decay narrative to the brief.
Those belong in PLAN.md 13.5 and in analysis, not in a daily bulletin.

## A report accuracy note, not a code change

Task 06's report listed as decision 8: *"Removed a duplicated summary.update block in build()."*
That block was not removed — the evening wiring was inserted between the two copies and both
remained. Values were identical, so nothing broke, and it has since been deleted in review.

Everything in these reports is checked. Report what the diff actually contains; a claim that a
change was made is more expensive to unpick than the change itself.

## The checks

1. After-dark zero with daylight flags present renders the mandated sentence.
2. After-dark zero with no daylight flags also renders it.
3. An after-dark flag is listed individually and is never summarised away.
4. Daylight flags render as one summary line, never enumerated.
5. The largest after-dark anomaly line always carries the "not a detection" clause.
6. No single combined flag count appears as the section's headline figure.
7. The existing 57 tests still pass.

## Out of scope

The Parquet producer, thresholds, cloud masking, the previous-evening scoping (correct as built),
the dashboard. No new dependencies.

## Before you finish

Name every decision this task did not specify, per AGENTS.md.
