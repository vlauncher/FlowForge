# Concept: state machines and invariants

**Definition.** A state machine lists states and the *only* allowed transitions between them. An invariant is a rule that holds in every reachable state.

**Failure it prevents.** Illegal transitions (e.g. `SUCCEEDED → RUNNING`), double completion, and a cancel racing a completion with unclear results.

**FlowForge run states.** `QUEUED → RUNNING → WAITING_APPROVAL / SUCCEEDED / FAILED / CANCELLED`. Transitions are monotonic toward terminal states.

**How it is enforced.**
1. Pure domain function `transition(state, event) → state | error` (unit-tested, deterministic).
2. A conditional database update: `UPDATE ... SET state='RUNNING' WHERE id=:id AND state='QUEUED'`. Zero rows updated means someone else won.
3. Check constraints on valid state values.

**Experiment.** Property-based test (Hypothesis): random event sequences never reach an illegal state.

**Trade-offs.** More code than a status string, but races become impossible to ignore.
