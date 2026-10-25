"""Prompt template loader and untrusted input wrapper."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import yaml  # type: ignore[import-untyped]

PROMPTS_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class PromptTemplate:
    id: str
    version: int
    system: str
    user: str

    def format_system(self) -> str:
        return self.system.strip()

    def format_user(self, input_text: str, *, labels: list[str] | None = None) -> str:
        # Sanitize delimiter breakout attempts
        sanitized_input = (
            str(input_text)
            .replace("</untrusted_input>", "&lt;/untrusted_input&gt;")
            .replace("<untrusted_input>", "&lt;untrusted_input&gt;")
        )

        formatted = self.user.replace("{{ input }}", sanitized_input)
        if labels is not None:
            formatted = formatted.replace("{{ labels }}", json.dumps(labels))
        return formatted.strip()


def load_prompt_templates(dir_path: Path | None = None) -> dict[str, PromptTemplate]:
    """Load and validate all YAML prompt templates in the specified directory."""
    target_dir = dir_path or PROMPTS_DIR
    templates: dict[str, PromptTemplate] = {}

    for yaml_file in sorted(target_dir.glob("*.yaml")):
        with open(yaml_file, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            continue

        template_id = data.get("id")
        version = data.get("version")
        system_text = data.get("system")
        user_text = data.get("user")

        if (
            isinstance(template_id, str)
            and isinstance(version, int)
            and isinstance(system_text, str)
            and isinstance(user_text, str)
        ):
            templates[template_id] = PromptTemplate(
                id=template_id,
                version=version,
                system=system_text,
                user=user_text,
            )

    return templates


# Global cache loaded at startup
PROMPT_TEMPLATES: dict[str, PromptTemplate] = load_prompt_templates()
known_prompt_templates: set[str] = set(PROMPT_TEMPLATES.keys())


def get_prompt_template(template_id: str) -> PromptTemplate:
    """Retrieve a loaded prompt template by id, raising KeyError if not found."""
    if template_id not in PROMPT_TEMPLATES:
        # Reload in case templates were added or updated
        refreshed = load_prompt_templates()
        if template_id in refreshed:
            PROMPT_TEMPLATES.update(refreshed)
            known_prompt_templates.clear()
            known_prompt_templates.update(PROMPT_TEMPLATES.keys())
            return PROMPT_TEMPLATES[template_id]
        avail = list(PROMPT_TEMPLATES.keys())
        raise KeyError(f"Prompt template '{template_id}' not found. Available: {avail}")
    return PROMPT_TEMPLATES[template_id]
