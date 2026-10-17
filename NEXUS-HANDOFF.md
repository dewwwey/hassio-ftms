# Engineering checkpoint: scoped Finish and reconnect repair

No personal observations, identifiers, credentials or raw logs are included.

Real-device acceptance now covers a clean observed recording, deterministic
summary replay, and an interrupted recording that preserves identity and flags
the unknown gap. No reward ledger was changed. Complete quality is an observation
property; intent remains unconfirmed.

A subsequent recovery failure is reproduced and remains under investigation.
A controlled power-loss test exposed an unmarked synchronous reconnect timer:
HA dispatched it to an executor, then rejected its event-loop-only reload call.
Version 0.24.8.dev2 marks that timer as a HA callback and checks shutdown state.
It passes 38 local tests, including this regression. Repeated live recovery is
still required; a single successful power cycle is insufficient acceptance.
Separate host diagnostics identify a missing Broadcom firmware patch. That is
not proof that firmware caused the observed failure. Independent
discovery on a Windows PC saw the bike when HA did not.

The administrator requested a usable Finish procedure while leaving FTMS enabled.
Schema 2 therefore declares `read_only=false`, `telemetry_observed=true`,
`automatic_control=false`, and `control_scope=["finish_workout"]`. The only
application writes are explicit Request Control (00) then Stop (08 01), each
requiring a matching successful indication. No automatic start/stop, resistance,
power target or reset. Request Control succeeds on the real idle device; Stop
times out in that idle state. A post-ride Finish remains unverified. Do not infer
device completion from a button's existence or from disconnection.

Consumers must use observed telemetry, quality, flags, storage health and intent
gates, rather than rejecting or approving evidence from `read_only` alone.
Stable ID derivation is unchanged. Replay adds schema metadata and finish reason;
source facts and IDs remain stable. No monetary or eligibility fields return.

## Reply to REQUEST-HA-SESSIONS-01

`ftms.get_sessions` is an HA action, not an MCP tool name. Its exact route through
the current management server is:

```python
ha_call_write_tool(name="ha_call_service", arguments={
    "domain": "ftms", "service": "get_sessions",
    "data": {"config_entry_id": FTMS_CONFIG_ENTRY_ID, "offset": 0, "limit": 50},
    "return_response": True,
})
```

Discover the entry with `ha_get_integration(domain="ftms")`. The action itself
only reads completed recordings. The MCP server categorizes all `ha_call_service`
calls as write tools and rejects its read proxy; that classification does not
make this action write a ledger. A client limited to MCP read tools needs the MCP
maintainer to add a dedicated wrapper. Do not expand permissions merely to work
around the category. This patch does not register MCP tools.

## Offline status and resets

`last_received_ts` is retained while the loaded coordinator is disconnected.
If HA unloads the entry or starts while the bike is absent, restored entities may
have only `restored=true`; persisted offline last-seen metadata is still open.
Never treat those restored attributes as current observations. Current metric
expiry and config-entry unload/reload can both cause `unavailable`; sensor
history alone does not distinguish their cause.

A real cumulative time/distance regression splits the active observation with
`counter_reset`, creating a different ID only on later positive cadence. A zero
at idle without positive cadence never creates a session. Disconnect/restart
alone preserve an active ID and exclude unknown intervals. Use completed-session
facts and flags, rather than reconstructing workouts from elapsed-sensor history.

The pre-existing `bike_gamification` entities and separate ledger changes remain
outside this component. Their presence alone does not prove active ledger writes;
their automations/scripts need a separate audit by the ledger owner.
