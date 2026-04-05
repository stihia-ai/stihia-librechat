# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## v0.1.0 - 2026-04-05

### Added

- Transparent HTTP proxy with Stihia realtime threat detection for OpenAI
  providers.
- Streaming and non-streaming support with input/output guardrails.
- Docker Compose stack bundling LibreChat, MongoDB, Meilisearch, RAG API
  (pgvector), and the Stihia AI security proxy.
- `librechat.yaml` with custom endpoints routing through the proxy.
- Community health files: CONTRIBUTING, CODE_OF_CONDUCT, SECURITY.
- GitHub issue and PR templates.
- CI pipeline (GitHub Actions) with lint, type check, and tests on
  Python 3.12 and 3.13.
