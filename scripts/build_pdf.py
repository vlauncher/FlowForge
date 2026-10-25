"""Build PDFs from flowforge.md and spec/.

Run with the project-local venv:
  .venv-docs/bin/python scripts/build_pdf.py --phase N   # docs/pdf/FlowForge-Phase-NN.pdf
  .venv-docs/bin/python scripts/build_pdf.py --all       # docs/pdf/FlowForge-Complete.pdf

A phase PDF holds:
  1. That phase's learning section from flowforge.md
  2. That phase's exact build specification from spec/phase-NN.md
  3. The Global Specification from spec/00-global.md
  4. The "## Shared:" sections from flowforge.md
"""

from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path

import markdown
from weasyprint import HTML

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
SPEC = ROOT / "spec"

CSS = """
@page { size: A4; margin: 22mm 18mm; @bottom-center { content: "FlowForge Guide - page " counter(page); font-size: 9pt; color: #666; } }
body { font-family: 'DejaVu Sans', sans-serif; font-size: 10pt; line-height: 1.45; color: #1a1a1a; }
h1 { font-size: 20pt; border-bottom: 2px solid #2b5fab; padding-bottom: 4px; page-break-before: always; }
h2 { font-size: 14pt; color: #2b5fab; margin-top: 18px; }
h3 { font-size: 11.5pt; }
table { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 8.5pt; }
th, td { border: 1px solid #bbb; padding: 4px 6px; vertical-align: top; text-align: left; }
th { background: #eef2f9; }
pre { background: #f5f5f5; border: 1px solid #ddd; padding: 8px; font-size: 8pt; white-space: pre-wrap; word-wrap: break-word; }
code { font-family: 'DejaVu Sans Mono', monospace; font-size: 8.5pt; background: #f2f2f2; padding: 0 2px; }
pre code { background: none; }
pre.mermaid { border-left: 4px solid #2b5fab; }
.diagram-label { font-size: 8pt; color: #2b5fab; font-weight: bold; margin-top: 8px; }
.cover { text-align: center; padding-top: 70mm; }
.cover h1 { border: none; page-break-before: avoid; font-size: 30pt; }
.toc li { margin: 2px 0; }
"""


def render(md_text: str) -> str:
    html = markdown.markdown(md_text, extensions=["tables", "fenced_code", "sane_lists"])
    return re.sub(
        r'<pre><code class="language-mermaid">',
        '<div class="diagram-label">Diagram (Mermaid source)</div><pre class="mermaid"><code>',
        html,
    )


def build(phase: int | None) -> None:
    text = (ROOT / "flowforge.md").read_text(encoding="utf-8")
    chunks = re.split(r"(?m)^(?=## )", text)
    preamble, sections = chunks[0], chunks[1:]
    picked: list[str] = []
    toc: list[str] = []

    for sec in sections:
        head = sec.splitlines()[0]
        m = re.match(r"## Phase (\d+):", head)
        if m:
            pnum = int(m.group(1))
            if phase is None or pnum == phase:
                picked.append(re.sub(r"^## ", "# ", sec, count=1))
                toc.append(head.lstrip("# "))
                spec_path = SPEC / f"phase-{pnum:02d}.md"
                if spec_path.exists():
                    spec_text = spec_path.read_text(encoding="utf-8")
                    picked.append(spec_text)
                    spec_head = spec_text.splitlines()[0].lstrip("# ")
                    toc.append(spec_head)
        elif phase is None or head.startswith("## Shared:"):
            picked.append(re.sub(r"^## ", "# ", sec, count=1))
            toc.append(head.lstrip("# "))

    if phase is not None and not toc:
        sys.exit(f"phase {phase} not found in flowforge.md")

    global_spec = SPEC / "00-global.md"
    if global_spec.exists():
        gtext = global_spec.read_text(encoding="utf-8")
        picked.append(gtext)
        toc.append(gtext.splitlines()[0].lstrip("# "))

    body = "\n\n".join(picked)
    title = "Complete Guide & Build Spec" if phase is None else f"Phase {phase} Guide & Build Spec"
    name = "FlowForge-Complete.pdf" if phase is None else f"FlowForge-Phase-{phase:02d}.pdf"
    cover = (
        f'<div class="cover"><h1>FlowForge</h1><h2>{title}</h2>'
        f"<p>AI Agent and Durable Workflow Automation Platform</p><p>Built {datetime.date.today()}</p></div>"
        '<h1>Contents</h1><ol class="toc">' + "".join(f"<li>{t}</li>" for t in toc) + "</ol>"
    )
    intro = render(
        preamble.replace(
            "# FlowForge: Complete Learn-and-Build Plan (Phases 1–10)", "# About this guide", 1
        )
    )
    doc = f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{cover}{intro}{render(body)}</body></html>"
    out = DOCS / "pdf" / name
    out.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=doc, base_url=str(DOCS)).write_pdf(out)
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", type=int)
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    if not (args.phase or args.all):
        ap.error("use --phase N or --all")
    build(args.phase)


if __name__ == "__main__":
    main()
