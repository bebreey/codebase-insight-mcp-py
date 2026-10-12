"""Credential scanning: detection, redaction, suppression."""

from __future__ import annotations

from codebase_insight.core import secrets

FAKE_AWS_KEY = "AKIA" + "IOSFODNN7REALKEY"


def test_reports_the_canonical_fake_aws_key_as_nothing() -> None:
    # AWS's own documented example key. Reporting it is the classic false positive.
    assert secrets.scan("a.py", 'KEY = "AKIAIOSFODNN7EXAMPLE"\n') == []


def test_detects_a_github_token_and_never_echoes_it() -> None:
    token = "ghp_" + "A" * 36
    findings = secrets.scan("a.py", f'TOKEN = "{token}"\n')

    assert len(findings) == 1
    assert findings[0].rule == "github-token"
    assert findings[0].severity == secrets.HIGH
    assert findings[0].fingerprint != token
    assert findings[0].fingerprint.startswith("ghp_")
    assert "*" in findings[0].fingerprint


def test_detects_an_embedded_private_key_as_critical() -> None:
    findings = secrets.scan("key.pem", "-----BEGIN RSA PRIVATE KEY-----\n")
    assert findings[0].severity == secrets.CRITICAL


def test_ignores_indirection_and_placeholder_vocabulary() -> None:
    assert secrets.scan("a.py", "KEY = os.environ['API_KEY']\n") == []
    assert secrets.scan("a.py", 'api_key = "your_api_key_here"\n') == []
    assert secrets.scan("a.py", 'api_key = "xxxxxxxxxxxxxxxxxxxx"\n') == []
    assert secrets.scan("a.py", 'password = "aaaaaaaaaaaa"\n') == []


def test_flags_a_credential_assigned_to_a_secret_looking_name() -> None:
    findings = secrets.scan("a.py", 'API_KEY = "notarealvalue12345678"\n')
    assert len(findings) == 1
    assert findings[0].rule == "generic-assigned-secret"
    assert findings[0].severity == secrets.MEDIUM


def test_downgrades_findings_in_a_test_path() -> None:
    findings = secrets.scan("tests/unit/a.py", '"-----BEGIN PRIVATE KEY-----"\n')
    assert findings[0].severity == secrets.HIGH  # critical -> high inside tests


def test_redaction_keeps_a_readable_fingerprint() -> None:
    assert secrets.redact("abc") == "***"

    masked = secrets.redact(FAKE_AWS_KEY)
    assert masked.startswith("AKIA")
    assert masked.endswith("EY")
    assert len(masked) == len(FAKE_AWS_KEY)
    assert set(masked[4:-2]) == {"*"}
    assert FAKE_AWS_KEY not in masked


def test_suppression_directive_on_the_same_line() -> None:
    source = f'TOKEN = "{FAKE_AWS_KEY}"  # {secrets.SUPPRESSION_DIRECTIVE}\n'
    assert secrets.scan("a.py", source) == []


def test_suppression_directive_on_the_line_above() -> None:
    source = f"# {secrets.SUPPRESSION_DIRECTIVE}\nTOKEN = '{FAKE_AWS_KEY}'\n"
    assert secrets.scan("a.py", source) == []


def test_suppression_directive_does_not_leak_past_the_next_line() -> None:
    source = "\n".join(
        [
            f"# {secrets.SUPPRESSION_DIRECTIVE}",
            f"first = '{FAKE_AWS_KEY}'",
            "second = 'AKIA" + "IOSFODNN7REALKEZ'",
        ]
    )
    findings = secrets.scan("a.py", source)
    assert len(findings) == 1
    assert findings[0].line == 3


def test_suppression_accepts_the_long_form_spelling() -> None:
    source = f"TOKEN = '{FAKE_AWS_KEY}'  # codebase-insight-ignore-secret\n"
    assert secrets.scan("a.py", source) == []


def test_identifies_sensitive_filenames_without_reading_them() -> None:
    assert secrets.match_sensitive_file(".env").rule == "dotenv-file"
    assert secrets.match_sensitive_file("config/.env.local").rule == "dotenv-file"
    assert secrets.match_sensitive_file("certs/server.pem").severity == secrets.CRITICAL
    assert secrets.match_sensitive_file("config/service-account-prod.json").rule == "service-account-json"
    assert secrets.match_sensitive_file(".npmrc").rule == "registry-auth"
    assert secrets.match_sensitive_file("src/index.py") is None
