# AI Use — HW8

1. What I used AI for and what I did myself. I used an AI coding assistant to help write and debug the Kafka worker, client, FastAPI wrapper, the three agents and the failure-test scripts. I ran the Docker stack, the demo, the agents in separate terminals and the failure tests myself, took the screenshots, checked the results against the assignment, and wrote the report.

2. One AI output that was wrong. The first version of the worker printed "Consumer is ready and listening..." after a loop that polled Kafka until the consumer got its partition. Any request that arrived during that loop was read and thrown away, so it would never get a response.

3. How I found it. Reading the worker code, I saw that the messages returned by that waiting loop were ignored. A request sent while the worker was still starting would have timed out on the client side.

4. What I changed. The ready message is now logged from the Kafka on_assign callback, so the worker never polls a message it does not process. Reply readers instead assign their partition at an explicit offset (the current end), so a response produced right after the request is always seen.
