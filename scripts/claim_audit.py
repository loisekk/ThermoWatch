#!/usr/bin/env python3
"""Claim-safety grep-gate (SIH26162 KB §24).

Fails on forbidden capability claims in client/src + server/api/app and EXPLAINS
the allowed phrasing. Whitelists the honest wording already used across the app:
  - near-real-time / near real-time   (FIRMS 3-6 h latency is disclosed)
  - explicit negations ("never claim real-time", "no real-time claim", ...)
Comments and docstrings about renderer internals ("preventDefault") are left
alone; only user-facing claim sentences are audited.

The scanned roots are anchored to THIS script's location (repo root), so the
gate behaves identically no matter the caller's working directory. If the walk
finds zero files, the gate FAILS — a scan of nothing must never pass.

Usage:  python scripts/claim_audit.py        (from anywhere)
"""
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ROOTS = [REPO_ROOT / "client" / "src", REPO_ROOT / "server" / "api" / "app"]
SKIP_DIRS = {"__pycache__", "node_modules", ".venv", ".git"}
SKIP_PREFIXES = ("//", "#", "*", "/*", "*/")

NEGATIONS = (
    "never claim", "never said", "not claim",
    "do not claim", "don't claim", "must not say", "cannot claim",
)
# A negation word sitting DIRECTLY before the match ("not real-time",
# "never claim real-time", "latency, not real-time") — the match itself
# consumes "real", so these can only be seen via this adjacency check.
NEG_ADJACENT = re.compile(
    r"\b(not|no|never|isn't|is not|far from|instead of|rather than)"
    r"(\s+(claim|real|said))?\s*$",
    re.IGNORECASE,
)

REAL_TIME = re.compile(r"\breal[\s-]?time\b", re.IGNORECASE)
NEG_WINDOW = 40  # chars of context before the match checked for whitelists

PATTERNS = [
    (re.compile(r"\bnovel\b", re.I), "claim-safety: avoid 'novel' — say 'integrated approach'"),
    (re.compile(r"\bfirst-of-its-kind\b|\bfirst-ever\b|\bindustry[- ]first\b"
                r"|\bthe first to (detect|classify|build|solve|implement|provide|use|deploy)\b", re.I),
     "claim-safety: avoid unsupported 'first' claims"),
    (re.compile(r"\bprevents?\b", re.I), "claim-safety: say 'supports/intervenes' not 'prevents'"),
    (re.compile(r"\b100\s?%\s*accuracy\b|\bperfect accuracy\b|\balways correct\b", re.I),
     "claim-safety: report specific F1/precision/recall"),
    (re.compile(r"\bguarantees?\b", re.I), "claim-safety: avoid 'guarantee'"),
    # Session 23 (LIVE WIRE): open-source news feeds are near-real-time wire
    # corroboration, never verification/confirmation; plumes are illustrative,
    # not dispersion models. Lookbehind guards keep our own honest phrasing legal.
    (re.compile(r"(?<!near[- ])real[\s-]?time\s+(news|wire|newsfeed|stream)", re.I),
     "claim-safety: 'real-time news/wire/stream' must be 'near-real-time wire' (provider latency 15 min-6 h)"),
    (re.compile(r"news\s+(confirms|verifies|proves)", re.I),
     "claim-safety: news corroborates, never confirms/verifies/proves"),
    (re.compile(r"(?<!not a )dispersion model", re.I),
     "claim-safety: plumes are illustrative, not a dispersion model"),
]


def bad_realtime(line: str) -> bool:
    """True when 'real-time' is asserted as a capability (not near-/negated)."""
    text = line.lower()
    for m in REAL_TIME.finditer(text):
        before = text[max(0, m.start() - NEG_WINDOW):m.start()]
        if "near" in before:
            continue
        if any(neg in before for neg in NEGATIONS):
            continue
        if NEG_ADJACENT.search(before):
            continue
        return True
    return False


def audit_file(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (UnicodeDecodeError, OSError):
        return errors
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped:
            continue
        if any(stripped.startswith(p) for p in SKIP_PREFIXES):
            continue
        if bad_realtime(line):
            errors.append(f"{path}:{i}: claim-safety: 'real-time' must be 'near-real-time' (FIRMS 3-6 h latency)")
        for rx, msg in PATTERNS:
            if rx.search(line):
                errors.append(f"{path}:{i}: {msg}")
    return errors


def collect_files() -> list[Path]:
    files: list[Path] = []
    for root in ROOTS:
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if p.is_file() and p.suffix in {".ts", ".tsx", ".py"}:
                if any(part in SKIP_DIRS for part in p.parts):
                    continue
                files.append(p)
    return files


def main() -> int:
    try:
        reconfigure = getattr(sys.stdout, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass  # non-Windows / redirected stdout already handled
    files = collect_files()
    if not files:
        print("\u274c Claim audit FAILED: scanned 0 files - check repo layout "
              f"(expected {ROOTS[0]} and {ROOTS[1]})")
        return 2
    bad = [e for f in files for e in audit_file(f)]
    if bad:
        print("\u274c Claim audit FAILED:")
        for e in bad:
            print(f"  {e}")
        return 1
    print(f"\u2705 Claim audit PASSED ({len(files)} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())