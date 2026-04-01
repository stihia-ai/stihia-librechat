# Contributing to Stihia LibreChat

Thank you for your interest in contributing! This guide explains how to get
involved and what to expect when you submit a change.

## Project Scope

This repository covers the Stihia AI security proxy for LibreChat and its
Docker Compose deployment stack. Contributions that fit this scope are welcome:

- Bug fixes and improvements to the proxy service.
- New provider adapters or guardrail integrations.
- Documentation improvements.
- CI/CD and developer tooling enhancements.
- Docker and deployment configuration.

The Stihia AI security engine itself (the Stihia API and the [`stihia`](https://github.com/stihia-ai/stihia-sdk-python) Python SDK package) and
LibreChat core are maintained separately. For issues with those projects,
please file upstream.

## Response Times

- **Issues:** We aim to triage new issues within **7 days**.
- **Pull requests:** You can expect an initial review within **14 days**.
  Complex changes may take longer.
- **Security reports:** Acknowledged within **3 business days** (see
  [SECURITY.md](SECURITY.md)).

## Code of Conduct

This project follows a [Code of Conduct](CODE_OF_CONDUCT.md). By
participating you agree to uphold its terms.

## Reporting Bugs

Open a [Bug Report](https://github.com/stihia-ai/stihia-librechat/issues/new?template=bug_report.md)
and fill in the template. Include:

- Steps to reproduce the issue
- Expected vs actual behaviour
- Python version, OS, and Docker version (if applicable)
- Relevant log output

## Suggesting Features

Open a [Feature Request](https://github.com/stihia-ai/stihia-librechat/issues/new?template=feature_request.md)
and describe the use-case you have in mind.

## Development Setup

```bash
# Clone the repository
git clone https://github.com/stihia-ai/stihia-librechat.git
cd stihia-librechat

# Install uv (if you don't have it)
# See https://docs.astral.sh/uv/getting-started/installation/

# Create and activate a virtual environment
uv venv
source .venv/bin/activate

# Install dependencies (including dev extras)
uv sync --extra dev
```

## Running Tests

```bash
uv run pytest tests -v
```

## Linting and Type Checking

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

Fix auto-fixable lint issues with:

```bash
uv run ruff check --fix .
uv run ruff format .
```

## Submitting a Pull Request

1. Fork the repository and create a feature branch from `main`.
2. Make your changes in small, focused commits.
3. Add or update tests to cover your changes.
4. Ensure all checks pass (`pytest`, `ruff`, `mypy`).
5. Open a pull request against `main` using the
   [PR template](.github/PULL_REQUEST_TEMPLATE.md).
6. Describe **what** changed and **why** in the PR description.

Pull requests are reviewed by at least one maintainer before merging.

## Coding Standards

- **Python ≥ 3.12** — the project targets Python 3.12+.
- **Ruff** for linting and formatting (line length 120).
- **Type hints** are expected for public APIs; `mypy` runs in CI.
- Keep dependencies minimal — add new packages only when necessary.

## Security Vulnerabilities

If you discover a security vulnerability, please follow the process described
in [SECURITY.md](SECURITY.md). **Do not** open a public issue for security
reports.

## License

By contributing you agree that your contributions will be licensed under the
[Apache License 2.0](LICENSE).
