# AI Use — HW7

1. What I used AI for and what I did myself. I used an AI coding assistant to help write parts of the code and debug problems. I chose Capital Bikeshare and its 30-day membership, designed the fixed agent tasks, the verifiers, the attack fixture and the safety-gate test commands, ran the experiments, and checked all results before using them.

2. One AI output that was wrong. The first version of the bash safety gate allowed the command `echo pwned >| /etc/hosts`. It split commands on every `|` character, so the `>|` redirection was cut in half and the check for writing to a root path never saw it.

3. How I found it. My 10-command safety-gate test marked that command as a false allow (9/10 correct). The result is saved in `reports/hw07/raw/safety_gate_results_v1.json`.

4. What I changed. The splitter no longer splits on the `|` of a `>|` redirect, and the redirect check now also catches `>|` and `&>`. I re-ran the same test and all 10 commands were correct; unit tests now cover this case.
