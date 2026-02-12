# Security Policy

## Supported Versions

We support the latest LTS of Django (5.2) and above.
Our libraries `django-program` and `pretalx-client` will revolve around this.

They are both versioned with semver, so breaking changes are (best-effort) guaranteed to happen in major version bumps only.
In other words:

| Version | Breaking Changes          |
| ------- | ------------------ |
| 1.0 -> 1.2   | No |
| 1.2 -> 2.0   | Yes                |
| 1.2 -> 1.2.3   | No |

## Reporting a Vulnerability

Report via GHSA: https://github.com/JacobCoffee/django-program/security/advisories/new
