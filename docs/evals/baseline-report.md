# FlowForge Golden Evaluation Baseline Report

**Dataset Version:** `v1`  
**Dataset SHA-256:** `0fa82000c81179c484c973b3bd11ff9f07013924bf473a1d6e8e8d19a31b0820`  
**Total Frozen Cases:** `30`  

---

## Baseline Benchmark Results

| Metric | Reference Baseline | Drifted Variant | Target Invariant |
|---|---|---|---|
| **Pass Rate** | **100.0%** (30/30) | 90.0% | &ge; 95.0% |
| **Invalid Output Count** | 0 | 1 | 0 |
| **Unsafe Tool Calls** | 0 | 0 | 0 (Strict) |
| **p50 Latency (ms)** | 25.0 | 25.0 | &le; 100 ms (Mock) |
| **p95 Latency (ms)** | 25.0 | 25.0 | &le; 250 ms (Mock) |
| **Total Tokens** | 2805 | 2805 | Monitored |
| **Est. Cost (micro USD)** | 5610 | 5610 | Within Org Budget |

### Per-Label Precision & Recall (Reference)

| Label | Precision | Recall |
|---|---|---|
| `billing` | 1.000 | 1.000 |
| `bug` | 1.000 | 1.000 |
| `other` | 1.000 | 1.000 |

---

## Adversarial Prompt Injection Defense

5 adversarial prompt injection cases (instruction override, delimiter breakout, credential exfiltration, SSRF redirection, and schema tampering) were tested.
- In all adversarial scenarios, unsafe tool calling remained at **0**.
- Inputs inside `<untrusted_input>` were treated as raw text data without executing injected instructions.
