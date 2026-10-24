# The site is built by a small Python script, not a JavaScript toolchain

Splitting the page into a hub plus five themed pages means five pages sharing a
header, navigation, footer, map setup and two string tables. The conventional
answer is a static site generator such as Eleventy or Astro. We are not using
one. The shared chrome is roughly thirty lines per page, and both tools would
put Node.js and `node_modules` into a `daily` cron job that currently installs
seven Python packages and nothing else, so a Node failure some morning would
stop the site updating for reasons unrelated to wildfires. A short Python script
stamps the shared chrome into each page at generation time instead, adding no
dependency (AGENTS.md rule 7).

A client-rendered SPA was rejected for a stronger reason than cost. Readers on
Biak are on slow and metered connections, and server-rendered static HTML means
the words arrive without JavaScript having to run first.

## Consequences

PLAN.md section 9 specifies "a single `index.html`, no build step" and "No
React, no Vite, no bundler, no npm". The npm half still holds and is now
stronger. The single-file half does not: there are five pages and a generation
step. PLAN.md needs amending by its human maintainer.
