# DeepSignal AI triage

DeepSignal AI triage is an event-triggered watch assistant. It summarizes evidence,
ranks likely causes, and presents runbook checks. It is **advise only**. A write
action is converted into a proposal that needs human approval and is never run.

## Two tiers

```text
Tier 1: continuous deterministic health, QARTOD, and time checks
                              |
                              v event only
Tier 2: bounded context -> AI triage -> validated briefing or runbook fallback
```

Tier 2 runs for a held degraded or failed transition, an A1 or A2 alert, an
Explain request, or an end-of-watch digest. Repeated evidence reuses a cached
briefing. Every context item has a reference identifier. Missing or stale inputs
are identified as missing or stale rather than guessed.

## Two directions

```text
Outbound, this module: ship -> egress proxy or allowlisted provider HTTPS API
Inbound, separate #64: AI client -> VPN or LAN -> DeepSignal MCP gateway
```

Outbound requests never pass through the MCP gateway. The two paths share the
redaction, budget, secret-storage, and audit guard package only.

## Guided setup

Run `python -m contrib.deepsignal.ai_triage setup` and complete these steps:

1. Select a built-in API provider and request shape.
2. Enter the key without terminal echo. The key is stored outside YAML.
3. Set daily and monthly spending caps and the ship's token prices.
4. Send one small test request and review its plain-language result.
5. Preview the exact redacted context pack and removal counts for a stream.

Configuration errors name the setting, received value, expected value, and an
example. Configuration loading must use `yaml.safe_load`.

## Cost controls

The defaults are USD 2 per day, USD 30 per month, 8,000 input tokens per call,
and 1,000 output tokens per call. Calls are checked before sending and settled
against actual use afterward. When a cap is reached, the deterministic runbook
briefing appears immediately and says that no AI was used.

For example only, 40 briefings per day at about 7,000 tokens each use about
280,000 tokens per day. Multiply 0.28 by the input price per million tokens the
ship enters, then add output cost. This is an illustration, not a forecast.

## Offline and local behavior

When link health is down or the provider cannot be reached, the assistant gives
the runbook fallback immediately with an `AI pending` label. It queues at most
50 requests on disk, dropping the oldest when full. On reconnection it sends
only requests whose incidents remain open and still fit the caps.

An optional llama.cpp or Ollama server can answer using the OpenAI-compatible
shape while offline. It is disabled by default and its result is explicitly
labeled `local model`. If neither model answers, the fallback names the first
failing stage and lists its runbook causes in order with `no AI used`.

## Privacy, audit, and learning

Only the compact context pack leaves the ship. Redaction removes credentials,
tokens, passwords, private keys, email addresses, phone numbers, globally held
fields, and EEZ-held fields. Positions are rounded while inside an EEZ. Setting
`api.enabled: false` disables all provider calls for stricter cruise terms.

Briefings are hash-chained into the timeline with pack hash, model, token use,
cost, latency, and output. Recorded outcomes can produce proposed runbook diffs;
the assistant never edits a runbook itself. A real provider check must be run by
the lead outside the sandbox.
