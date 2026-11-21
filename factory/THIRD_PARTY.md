# Third-party code: Software Factory for Claude Code (v2)

The files in `factory/`, `.claude/skills/factory/` and the eight agents
`intake`, `spec-writer`, `builder`, `reviewer-code`, `reviewer-security`,
`reviewer-ux`, `reviewer-ui` and `approver` in `.claude/agents/` come from
ZazenCodes' Software Factory for Claude Code v2:

https://github.com/zazencodes/zazencodes-season-3/tree/main/src/software-factory-claude-code-v2
(commit 3b46a49ef0efa33a94c98db09a8738e3a161d1dd)

They are licensed under GPLv3 (`factory/LICENSE`), not under this repository's
own licence. Changes made here: `factory/checks.sh` and `factory/config.json`
were filled in for this project, `concurrency` was set to 1, and the intake and
approver agents each gained one project-specific line. The upstream author
offers a commercial licence for closed-source or commercial use.
