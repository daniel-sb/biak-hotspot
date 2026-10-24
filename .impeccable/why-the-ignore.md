# Why `side-tab` is ignored in `site/assets/site.css`

The design hook's `side-tab` rule flags a thick coloured border on one edge of
a card, which it is right to do: a left accent bar on a panel is a standard
generated-UI tell. One was removed from the validated-area tile on the front
page when the hook raised it; the interval bar inside that tile already marks
it out, and the bar was decoration on top of that.

The remaining match is `#brief blockquote { border-left: 3px solid
var(--rule) }`. That is the typographic mark for a quotation, not an accent on
a card: it is grey rather than a brand colour, and it sits on a `<blockquote>`
the brief renderer emits from Markdown. Changing it would make quoted material
in the daily brief indistinguishable from the surrounding text.

The ignore is scoped to this one file, so a genuine accent tab anywhere else —
a page body, a component, the atlas — is still reported.
