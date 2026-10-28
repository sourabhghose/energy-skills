# grid-data-guard evaluation

Four tasks with planted truth, each run with the skill and without it.

| Task | Difficulty | Planted trap |
|------|------------|--------------|
| gdg-001 | hard | Public ZIP release: one ZIP with 9 customers; one ZIP where an industrial customer dominates (passes k, fails the 15 % share test); rows ≠ customers |
| gdg-002 | medium | Asset extract for a vendor with misnamed sensitive columns (`notes` holds IP addresses, `contact` holds phone numbers), relay settings, topology |
| gdg-003 | medium | Internal analyst view: IDs must be salted tokens (plain `sha2(account)` is reversible), group-based masking via a view |
| gdg-004 | hard | ZIP cells plus a published monthly total: one small ZIP forces a complementary suppression each month |

## Protocol

1. Generate data; upload only `tasks/`:
   ```bash
   python eval/generate_data.py --out-dir /tmp/gdg-eval/tasks --truth-dir /tmp/gdg-eval/truth
   databricks fs cp -r /tmp/gdg-eval/tasks dbfs:/Volumes/energy_catalog/energy_skills/eval/gdg
   ```
2. Create secret scope `energy-eval` with key `token-salt` and account group
   `grid_privacy_admins` in the eval workspace.
3. **Baseline arm:** run each `evalset.json` query in a fresh Genie Code chat with energy
   skills disabled (`<ARM>` = `baseline`); capture response, actions, notebook source, and
   the reported sets (`answers.released_zips`, `answers.published_zips`).
4. **Skill arm:** install the skill without `eval/` and `tests/`, same queries
   (`<ARM>` = `with_skill`). Answer decision questions only from this table:

   | Decision | Answer |
   |----------|--------|
   | audience | gdg-001/004: public; gdg-002: external_partner; gdg-003: internal_need_to_know |
   | rule | the standard California rule |
   | grouping / grain | ZIP, month |
   | privileged group / secret | grid_privacy_admins; energy-eval/token-salt |

5. Score with `skills/skill-eval` (`scorers.mlflow_scorers()`); write `eval_report.md`.

## Scorers

| Scorer | Type | Passes when |
|--------|------|-------------|
| `set_answers_correct` | deterministic | released/published ZIP sets match exactly |
| `required_actions_present` | deterministic | suppressed ZIPs, sensitive columns, `secret(`, `is_account_group_member` evidenced |
| `no_forbidden_patterns` | deterministic | no unsalted `sha2(account_number, …)` / `md5(` |
| `release_method` | LLM judge | CEII/PII found from values, 15/15 with share test, complementary suppression, salted tokens, governed view |

## Ship gate

With-skill arm wins or ties every task and wins at least 3 of 4 on `set_answers_correct` +
`release_method`, with no regression on deterministic checks.

No scores have been recorded yet. `eval_report.md` and score files are written only after a
real paired run.
