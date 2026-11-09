# CB33 P07 SPEC v1.1 — owner revised and approved 2026-11-09
R1: Pass the COMPLETE executor answer unmodified as one continuous string in ONE Supervisor message. Specifically preserve all 130,000+ characters and final marker. No chunking, summarization, pagination or hidden 12k/48k cutoffs.
R2: Bind prompt to original request, full answer SHA256 and assistant message ID. A single model has finite context: if external model/browser rejects oversized text, report explicit failure and remain blocked/uncertain, without truncating or submitting a reduced answer.
R3: ChatBridge owner gateway currently rejects >100,000 characters in media.parse_message; remove this arbitrary character cap (HTTP server's existing 70MiB body-size bound stays). Verify 130k+ entire contents reach session engine without normalization/cropping.
R4: Recipient-specific notification B may run with unrelated A streaming if target chat idle, gateway active=1/capacity10, no provider HTTP429 and one delivery per cycle; reject target busy, capacity saturation, active>=2 or cooldown.
R5: Keep preexisting BF33 tasks unchanged, preserve exact status/ACK/review identity/mandatory Supervisor authority. No unapproved retries.
R6: RED/GREEN 18,454 /130,000 /1,000,000-character one-shot messages and marker at end, explicit failure on oversized model context, notification admission, full offline tests, Converge, Git commits and owner-only rollback-able deploy.
R7: Low-load live E2E and final project re-pause, stop at HTTP429. Never imply infinite context.
