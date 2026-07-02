# Security Policy

## Reporting a vulnerability

Please do **not** report security vulnerabilities through public GitHub issues.

Instead, use [GitHub's private vulnerability reporting](https://github.com/Intelligent-Internet/zenith/security/advisories/new) for this repository. We will acknowledge your report within a few business days and keep you informed as we investigate and remediate.

## Scope

Zenith runs coding agents that can execute commands and modify files in the workspace you point them at. When reporting, issues of particular interest include:

- Escapes from the configured workspace directory by workers, testers, or validators
- Prompt-injection paths that cause the orchestrator to take actions outside its mission
- Unsafe handling of ACP subprocess input/output

## Supported versions

Security fixes are applied to the latest release on `main`.
