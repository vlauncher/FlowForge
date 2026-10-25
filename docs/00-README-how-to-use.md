# FlowForge Study Guide: How to Use This Library

**The main file is [`flowforge.md`](../flowforge.md)** at the repo root: the all-in-one plan for phases 1–10. Build from it. The files in `docs/` are supporting reference.

## Reading order
1. [`flowforge.md`](../flowforge.md): read a phase section **before** coding it, then code, then do the labs and self-test.
2. [Roadmap analysis](01-roadmap-analysis.md): what the source roadmap asks for.
3. [Software engineer growth](learning/software-engineer-growth.md): the skills you are training.
4. `concepts/`: reference notes whenever a term is unfamiliar.
5. [sources-studied](sources/sources-studied.md): the original documentation and papers, with check status.
6. `adr/`: architecture decision records, one per major decision.

## The per-phase study loop (from the roadmap)
read one primary source → run one small experiment → write one ADR or trade-off note → implement a vertical slice → make it fail on purpose → run tests → explain it without an AI assistant.

## PDFs
```bash
.venv-docs/bin/python scripts/build_pdf.py --phase N   # docs/pdf/FlowForge-Phase-NN.pdf
.venv-docs/bin/python scripts/build_pdf.py --all       # docs/pdf/FlowForge-Complete.pdf
```

## Rules of the library
- Every important decision has a **why**, a **rejected alternative**, and **the failure it prevents**.
- Performance numbers are hypotheses to measure, not facts.
- Sources are labelled as official docs, standards, preprints, or refereed papers. Recheck versions before relying on an API.
- Never put real API keys in a chat or in git. Use `.env` (git-ignored).
