# HW9 label notes (cache_cases.yaml)

`cache_cases.yaml` was written before the sweep and has not been edited since (sha256 `eb413fcb8db3f094…`
is recorded in `raw/sweep_results.json`; `make verify-hw09` re-checks it). No label was changed.

Observation after the sweep (not a relabel): the grounded Writer ends every answer with the full
`Source record:` line (affected range, severity, CVE, fixed version). So some false hits contain the needed
fact somewhere in the text - e.g. C25 asks for the first affected requests version (2.3.0) and the cached
fix-version answer mentions ">= 2.3.0" inside the range. They stay false hits: the answer addresses a
different question (it tells the user to upgrade to 2.31.0 and never says which version introduced the leak).
