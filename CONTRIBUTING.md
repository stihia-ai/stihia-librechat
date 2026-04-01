# Contributing to Stihia LibreChat

Thank you for your interest in contributing! This guide explains how to get
involved and what to expect when you submit a change.

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

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies (including dev extras)
pip install -e ".[dev]"
```

## Running Tests

```bash
pytest tests -v
```

## Linting and Type Checking

```bash
ruff check .
ruff format --check .
mypy src
```

Fix auto-fixable lint issues with:

```bash
ruff check --fix .
ruff format .
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
