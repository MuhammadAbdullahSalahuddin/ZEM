# AGENTS.md: rules for any AI working in this repo
- Project: ZEM, a zero-trust gateway between AI agents and MCP tools. Python 3.12, uv, pydantic v2.
- Read `src/zem/contracts/models.py` before writing anything. NEVER change it without being told.
- Edit only the files named in the task's "Allowed to edit" list.
- Never print to stdout inside `src/zem/protocol/` or `src/zem/cli/wrap`. stdout is the MCP channel. Log to stderr.
- Every change needs tests. Finish with `make check` passing.
- Security code (`detectors/`, `policy/`, `audit/`, `protocol/`): no clever shortcuts. Fail closed on parse errors.
- Ask when unsure. Do not invent APIs.
