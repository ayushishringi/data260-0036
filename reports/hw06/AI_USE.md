# AI Use — HW6

1. What I used AI for and what I did myself. I used an AI coding assistant to help write parts of the code, to debug problems. I designed the domain mapping, the memory probes and the cost method, ran the experiments, and checked all results before using them.

2. One AI output that was wrong. The first experiment script did not actually change the memory settings. It only labeled the runs, so all four "settings" in my first results table really used the same configuration (N=12).

3. How I found it. The N=4 run used about the same number of short-term tokens per turn as the N=30 run, which should be impossible for a 4-message window.

4. What I changed. The script now starts a fresh server for each setting and stops if the server reports a different setting. I re-ran all four settings, and the token counts now grow with the window size as expected.
