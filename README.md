# Math-Agent

A competition-grade mathematical reasoning harness built around the official Intern-S client.

The official `main.py` and `llm_client.py` files are frozen and verified byte-for-byte. Participant code is exposed through `user_agent.ReasoningAgent`.

## Baseline verification

```bash
python scripts/verify_baseline_files.py
pytest -q
```
