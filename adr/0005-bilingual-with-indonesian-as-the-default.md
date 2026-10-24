# Bilingual, with Indonesian as the default

PLAN.md section 7 ranks "a reliable, corroborated, plainly-worded daily hotspot
brief in Bahasa Indonesia" above everything else in the project. That was never
built: `docs/index.html` is `<html lang="en">` and every brief in `docs/briefs/`
is English. Serving Biak readers and reviewers equally makes the gap a blocker
rather than a shortfall.

The site is therefore bilingual with Indonesian as the default and `?lang=en`
for English. UI strings live in one JSON file per language instead of being
inlined twice, and `src/report.py` emits both `docs/briefs/id/` and
`docs/briefs/en/`. The methods page stays English only, because its audience is
reviewers and translating the S2DR4 band-order discussion serves nobody.

This is the largest implementation cost in the dashboard plan, which is why it
is sequenced last: the copy has to stop changing before it is worth
translating.

## Consequences

Claude drafts the Indonesian and the project owner, a Biak resident and native
speaker, reviews and corrects it. Two passages must not go live unreviewed: the
section 8 ethics paragraph, which decides whether the page reads as
documentation or as accusation when small-scale burning in Papua is lawful, and
the status strip, which is the one line telling people whether anything is
burning now.
