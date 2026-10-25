"""Static AST analyzer verifying tenant parameter isolation across repositories (P2-T30).

Every repository method interacting with tenant-scoped tables (`memberships`, `workflows`,
`workflow_versions`) must accept an `org_id` parameter.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TARGET_REPOSITORIES = [
    ROOT / "app/modules/organizations/repository.py",
    ROOT / "app/modules/workflows/repository.py",
    ROOT / "app/modules/executions/repository.py",
    ROOT / "app/modules/integrations/repository.py",
]

# Methods that operate purely on global entities (e.g. org by primary key or user-level list)
EXEMPT_METHODS = {
    "__init__",
    "get_by_id",  # OrganizationRepository.get_by_id fetches org by its own primary key
    "get_by_slug",  # OrganizationRepository.get_by_slug fetches org by unique slug
    "create_organization",
    "list_user_organizations",
    "get_by_id_for_user",  # Joins with membership table directly on org_id
}


def check_repository(filepath: Path) -> list[str]:
    errors = []
    tree = ast.parse(filepath.read_text(encoding="utf-8"), filename=str(filepath))

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name.endswith("Repository"):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    method_name = item.name
                    if method_name in EXEMPT_METHODS:
                        continue

                    param_names = [arg.arg for arg in item.args.args + item.args.kwonlyargs]
                    if "org_id" not in param_names:
                        errors.append(
                            f"{filepath.name}::{node.name}.{method_name} is missing required 'org_id' parameter! Found: {param_names}"
                        )
    return errors


def main() -> int:
    all_errors = []
    for repo_path in TARGET_REPOSITORIES:
        if not repo_path.exists():
            print(f"Error: {repo_path} does not exist", file=sys.stderr)
            return 1
        all_errors.extend(check_repository(repo_path))

    if all_errors:
        print("Tenant parameter static check FAILED:", file=sys.stderr)
        for err in all_errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print("Tenant parameter static check PASSED: all repository methods enforce org_id parameter.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
