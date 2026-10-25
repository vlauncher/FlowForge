"""Check flowforge.md, spec/00-global.md, spec/phase-01..10.md, and docs/ consistency."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
SPEC = ROOT / "spec"

FLOWFORGE_REQUIRED = [
    "Objective",
    "Concepts to learn",
    "Why these decisions",
    "Build tasks",
    "Acceptance",
    "Break-it labs",
    "Sources",
    "How this makes you a better engineer",
    "Self-test",
    "Done when",
]

SPEC_PHASE_REQUIRED = [
    "Scope",
    "Steps",
    "Files",
    "Test cases",
    "Verification commands",
    "Done when",
    "Agent brief",
]

EXPECTED_TABLES = {
    "users",
    "refresh_tokens",
    "organizations",
    "memberships",
    "workflows",
    "workflow_versions",
    "triggers",
    "integration_credentials",
    "workflow_runs",
    "step_attempts",
    "approval_requests",
    "tool_effects",
    "outbox_events",
    "usage_records",
    "budget_reservations",
    "audit_events",
}


def main() -> int:
    errors: list[str] = []

    # 1. Check flowforge.md phases
    text = (ROOT / "flowforge.md").read_text(encoding="utf-8")
    for n in range(1, 11):
        m = re.search(rf"(?ms)^## Phase {n}:.*?(?=^## |\Z)", text)
        if not m:
            errors.append(f"flowforge.md: phase {n} missing")
            continue
        for sub in FLOWFORGE_REQUIRED:
            if not re.search(rf"^### {re.escape(sub)}", m.group(0), re.M):
                errors.append(f"flowforge.md: phase {n} missing '### {sub}'")

    # 2. Check spec/00-global.md
    global_path = SPEC / "00-global.md"
    if not global_path.exists():
        errors.append("spec/00-global.md missing")
    else:
        gtext = global_path.read_text(encoding="utf-8")
        defined_tables = set(re.findall(r"(?m)^### ([a-z_]+) \(phase", gtext))
        missing_tables = EXPECTED_TABLES - defined_tables
        if missing_tables:
            errors.append(f"spec/00-global.md missing table definitions: {sorted(missing_tables)}")
        defined_error_codes = set(re.findall(r"(?m)^\| `([A-Z0-9_]+)` \| \d{3} \|", gtext))
        run_error_codes = set(
            re.findall(
                r"`([A-Z0-9_]+)`",
                re.search(r"\*\*Run `error_code` values\*\*.*", gtext).group(0)
                if "**Run `error_code` values**" in gtext
                else "",
            )
        )
        all_error_codes = defined_error_codes | run_error_codes

        # 3. Check spec/phase-01..10.md
        for n in range(1, 11):
            pfile = SPEC / f"phase-{n:02d}.md"
            if not pfile.exists():
                errors.append(f"spec/phase-{n:02d}.md missing")
                continue
            ptext = pfile.read_text(encoding="utf-8")
            for req in SPEC_PHASE_REQUIRED:
                if not re.search(rf"(?m)^## {re.escape(req)}", ptext):
                    errors.append(f"{pfile.name}: missing '## {req}'")
            if not re.search(rf"\bP{n}-S01\b", ptext):
                errors.append(f"{pfile.name}: missing step ID P{n}-S01")
            if not re.search(rf"\bP{n}-T01\b", ptext):
                errors.append(f"{pfile.name}: missing test ID P{n}-T01")
            if not re.search(rf"\bP{n}-F01\b", ptext):
                errors.append(f"{pfile.name}: missing frontend test ID P{n}-F01")

            # Verify any referenced HTTP error codes exist in global error catalog
            for code in re.findall(
                r"\b(?:400|401|402|403|404|405|409|413|422|429|500|503)\s+`([A-Z0-9_]+)`", ptext
            ):
                if code not in all_error_codes:
                    errors.append(
                        f"{pfile.name}: unknown error code '{code}' not in spec/00-global.md"
                    )

    # 4. Check internal Markdown links
    for md in [ROOT / "flowforge.md", *DOCS.rglob("*.md"), *SPEC.rglob("*.md")]:
        for target in re.findall(r"\]\(([^)#]+\.md)(?:#[^)]*)?\)", md.read_text(encoding="utf-8")):
            if not target.startswith("http") and not (md.parent / target).exists():
                errors.append(f"{md.relative_to(ROOT)}: broken link {target}")

    for e in errors:
        print("ERROR:", e)
    print("docs & spec check:", "FAILED" if errors else "OK")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
