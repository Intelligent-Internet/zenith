# Zenith repository guidance

- Codex ACP is subscription-only by default. Keep its managed `CODEX_HOME`
  ChatGPT-only with login shells and shell snapshots disabled; never restore ambient
  credential inheritance or the legacy danger-full-access command overrides.
- API-billed ACP tasks require both an explicit task `billing.api_grant` request and
  an exact, unexpired, non-revoked operator grant from `ZENITH_API_GRANTS_FILE`.
  Never store credential material in task JSON, receipts, prompts, or grant records.
- Keep ACP and Zenith MCP child environments allowlisted. Only the exact Codex ACP
  child for an authorized API task may receive `OPENAI_API_KEY`.
