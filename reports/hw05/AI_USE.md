# AI use disclosure

1. I used an AI assistant to inspect the HW4 repository, scaffold the HW5 API/MCP/tool-test structure, and review integration points. I selected the domain model, checked the assignment requirements, ran the verification commands, and remain responsible for the implementation and evidence.
2. One independently verified result was the fault-injection reproducibility claim and the MCP STDIO logging boundary.
3. I detected this by running the same seeded fault benchmark twice, comparing the machine-readable sequences, and checking that server logging is configured through Python logging rather than `print`.
4. I kept the seed explicit in every benchmark call and routed diagnostics through logging. The offline test suite also exercises invalid inputs, the safety rule, and the max-step ceiling without a model or network.
