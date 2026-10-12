"""Credential scanning.

Two rules shape the design:

1. Findings never echo the secret back. Every match is redacted to a
   fingerprint, so a report can be pasted into a ticket or a model context
   without leaking the credential it warns about.
2. Anything that looks like a template is suppressed, because a false positive
   here trains people to ignore the scanner.

Deliberate test data is silenced with an explicit ``cbi-ignore-secret`` comment
on the line, or on the line above. There is no file-wide escape hatch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CRITICAL = "critical"
HIGH = "high"
MEDIUM = "medium"

SUPPRESSION_DIRECTIVE = "cbi-ignore-secret"
_SUPPRESSION = re.compile(r"(?:cbi|codebase-insight)[-_ ]?ignore[-_ ]?secret", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Rule:
    id: str
    description: str
    severity: str
    pattern: re.Pattern[str]


@dataclass(frozen=True, slots=True)
class Finding:
    rule: str
    description: str
    severity: str
    file: str
    line: int
    fingerprint: str


RULES: tuple[Rule, ...] = (
    Rule(
        "aws-access-key-id", "AWS access key ID", HIGH, re.compile(r"\b(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b")
    ),
    Rule(
        "aws-secret-access-key",
        "AWS secret access key",
        CRITICAL,
        re.compile(r"aws_secret_access_key\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{40}['\"]?", re.IGNORECASE),
    ),
    Rule(
        "github-token",
        "GitHub personal access / app token",
        HIGH,
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    ),
    Rule("gitlab-token", "GitLab personal access token", HIGH, re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b")),
    Rule("slack-token", "Slack API token", HIGH, re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    Rule("google-api-key", "Google API key", HIGH, re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    Rule(
        "stripe-secret-key", "Stripe live secret key", CRITICAL, re.compile(r"\bsk_live_[0-9A-Za-z]{20,}\b")
    ),
    Rule(
        "openai-api-key",
        "OpenAI-style project key",
        HIGH,
        re.compile(r"\bsk-(?:proj|svcacct|admin)-[A-Za-z0-9_-]{20,}\b"),
    ),
    Rule("anthropic-api-key", "Anthropic API key", HIGH, re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    Rule(
        "private-key-block",
        "Embedded private key",
        CRITICAL,
        re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----"),
    ),
    Rule(
        "jwt",
        "Hard-coded JSON Web Token",
        MEDIUM,
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    ),
    Rule(
        "generic-assigned-secret",
        "Hard-coded credential assigned to a secret-looking name",
        MEDIUM,
        re.compile(
            r"(?:api[_-]?key|apikey|secret[_-]?key|client[_-]?secret|access[_-]?token"
            r"|auth[_-]?token|password|passwd|private[_-]?key)\s*[:=]\s*['\"](?P<value>[^'\"\s]{12,})['\"]",
            re.IGNORECASE,
        ),
    ),
)

# Placeholder vocabulary is deliberately *not* word-bounded: AWS's own example
# key `AKIAIOSFODNN7EXAMPLE` has no word boundary before EXAMPLE, and reporting
# it is exactly the false positive that makes a scanner ignorable.
_ALLOWLIST: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?:example|sample|placeholder|dummy|fake|redacted|changeme|replace[_-]?me|your[_-]|xxxx)",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:todo|fixme|hack)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:process\.env|import\.meta\.env|os\.environ|os\.getenv|getenv|environ\["
        r"|System\.getenv|ENV\[|vault|secretRef|secrets\.)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\$\{\{|\{\{|\$\{|<[A-Z_]{3,}>"),
    re.compile(r"\b(?:test|spec|fixture|mock|stub)\b", re.IGNORECASE),
)

_TEST_PATH = re.compile(
    r"(?:^|/)(?:tests?|specs?|__tests__|fixtures?|examples?|samples?|docs?)/", re.IGNORECASE
)


def redact(value: str) -> str:
    """``AKIAIOSFODNN7EXAMPLE`` -> ``AKIA************LE``."""
    trimmed = value.strip()
    if len(trimmed) <= 6:
        return "*" * len(trimmed)
    masked = "*" * min(16, max(4, len(trimmed) - 6))
    return f"{trimmed[:4]}{masked}{trimmed[-2:]}"


def _plausible(value: str) -> bool:
    if len(value) < 12:
        return False
    if re.fullmatch(r"(?:\*+|x+|X+|-+|\.+)", value):
        return False
    return len(set(value)) >= 5


def _suppressed(lines: list[str], index: int) -> bool:
    if _SUPPRESSION.search(lines[index]):
        return True
    return index > 0 and _SUPPRESSION.search(lines[index - 1]) is not None


def _downgrade(severity: str) -> str:
    return HIGH if severity == CRITICAL else MEDIUM


def scan(rel: str, text: str) -> list[Finding]:
    """Find credential-shaped strings in one file's content."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    findings: list[Finding] = []

    for index, line in enumerate(lines):
        if line == "":
            continue
        if any(pattern.search(line) for pattern in _ALLOWLIST):
            continue
        if _suppressed(lines, index):
            continue

        for rule in RULES:
            match = rule.pattern.search(line)
            if match is None:
                continue
            captured = match.groupdict().get("value")
            if captured is not None and not _plausible(captured):
                continue
            findings.append(
                Finding(
                    rule=rule.id,
                    description=rule.description,
                    severity=_downgrade(rule.severity) if _TEST_PATH.search(rel) else rule.severity,
                    file=rel,
                    line=index + 1,
                    fingerprint=redact(captured if captured is not None else match.group(0)),
                )
            )
            break  # one finding per line is enough to act on

    return findings


# Files that commonly carry credentials and should not be committed.
_SENSITIVE_PATTERNS: tuple[tuple[str, str, str, str], ...] = (
    ("dotenv-file", "Environment file (usually holds live credentials)", HIGH, r"^\.env(\..*)?$"),
    (
        "private-key-file",
        "Private key material",
        CRITICAL,
        r"\.(?:pem|p12|pfx|jks|keystore)$|^id_(?:rsa|dsa|ecdsa|ed25519)$",
    ),
    ("service-account-json", "Service account key file", CRITICAL, r"^service[-_]?account.*\.json$"),
    ("registry-auth", "Package registry auth file", MEDIUM, r"^\.npmrc$|^\.pypirc$|^\.netrc$"),
)


@dataclass(frozen=True, slots=True)
class SensitiveFile:
    rule: str
    description: str
    severity: str
    file: str


def match_sensitive_file(rel: str) -> SensitiveFile | None:
    base = rel.replace("\\", "/").rsplit("/", 1)[-1].lower()
    for rule_id, description, severity, pattern in _SENSITIVE_PATTERNS:
        if re.search(pattern, base):
            return SensitiveFile(rule=rule_id, description=description, severity=severity, file=rel)
    return None
