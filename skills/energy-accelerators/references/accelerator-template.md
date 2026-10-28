# Energy accelerator reference template

<!-- Adapted from databricks-industry-solutions/vital-skills (skills/accelerators/references/accelerator-template.md); modified for the energy industry. -->

Copy to `references/accelerators/<name>.md`, fill every section, and add a row to
`references/accelerators/index.md`. Keep stable facts only; link to the source for
step-by-step install text. `tests/test_accelerator_cards.py` enforces the fields below.

## Identity

- Name:
- Kind: accelerator | library | partner-solution | vendor-integration
- URL: <https URL that was opened and returned 200 on the review date>
- Install doc: <file in the repo, or page section>
- Maintainers: <team or "see repo contributors">
- Licence: <Databricks License | Apache-2.0 | vendor terms>
- Last updated: <YYYY-MM-DD of the latest commit or page update>
- Maturity: maintained | reference-only | stale (>18 months) | deprecated
- Reviewed: <YYYY-MM-DD> against commit <sha> (repos) or "page checked" (partner pages)

## Use it for

Tasks a user would ask for, in their words.

## Do not use it for

Nearby requests it does not cover, and the Energy Skill or accelerator to use instead.

## Data

What data it expects or generates (synthetic demo data vs. your own tables).

## Deploy signals

Jobs, apps, or tables that show it is already installed. Say "not documented" when the
README does not name them.

## Smallest path

The minimal way to get a working result.

## Pitfalls

Known failures not obvious from the README, each with the fix.

## Pair with Energy Skills

Which Energy Skills to use before, after, or instead.
