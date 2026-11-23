# AI Use — HW11

1. What I used AI for. I used an LLM to help with the code and the test fixtures.

2. One AI output that was wrong. The first day-1 EDGAR fixture had an XML comment that contained the text `--stop-after`. Two hyphens are not allowed inside an XML comment, so the file was not valid XML. watch.py logged one `source_error` and returned no filings, so the three day-1 8-Ks (the SNTL earnings filing and golden cases R1 and R2) silently disappeared from the scan.

3. How I found it. Before giving the kit to Muse, I ran a mechanics check (`make test-hw11`) that scans both test days in a throwaway copy and matches every golden case to an item. It reported R1 and R2 as `not_retrieved`, and the scan summary showed 0 items from edgar_demo instead of 3.

4. What I changed. I rewrote the comment without the double hyphen and checked every fixture file with Python's XML parser. The check then found all 12 cases, and only after that did I commit the labels and build the kit. The same silent-failure pattern (a source error that shows up only as "0 items") happened again in the live run on Muse, which is discussed in Part 1.1.
