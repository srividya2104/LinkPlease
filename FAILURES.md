# LinkPlease System Failure Modes & Analysis

This document provides a realistic engineering assessment of edge cases, failure scenarios, and boundaries under which this system could lose a DM, send a duplicate, or report inaccurate stats.

---

### 1. Hard Process Crash During In-Flight Outbound Send
- **Condition**: The application server receives a SIGKILL or unhandled power termination precisely after `POST /v1/dm/send` reaches PseudoGram but before the HTTP response is parsed and written to the SQLite database.
- **Impact**: Upon restart, the recovery logic sees the delivery in `sending` (or `pending`) state and re-attempts the send.
- **Mitigation**: We pass a deterministic, persistent `Idempotency-Key` (`rule:{rule_id}:user:{user_id}`). PseudoGram detects the duplicate key and returns the previously generated `dm_id` without re-sending the message.
- **Remaining Risk**: If PseudoGram's idempotency store experiences internal cache eviction or failure, a duplicate DM could theoretically be delivered.

---

### 2. Microsecond Race Condition on Duplicate Webhooks
- **Condition**: Two identical webhook payloads (`comment.created` for the same user and rule) arrive simultaneously within a ~1ms window across multi-worker threads or processes.
- **Impact**: Both workers evaluate `db.get_delivery_by_idempotency_key` simultaneously before either has committed an `INSERT` statement.
- **Mitigation**: The database schema enforces a strict `UNIQUE` index constraint on `deliveries.idempotency_key`. The second worker's `INSERT` query fails with an `IntegrityError`, triggering `increment_duplicates_blocked()` instead of creating a second delivery.
- **Remaining Risk**: If the application is scaled horizontally across multiple instances using local SQLite databases (instead of a shared PostgreSQL cluster), duplicate checks would not be shared across node boundaries.

---

### 3. Non-Persistent Storage on Container Redeployments
- **Condition**: The application is deployed on stateless container infrastructure (e.g., Render standard instances without persistent disk attachments) and undergoes a deployment or container restart.
- **Impact**: The local SQLite database file (`linkplease.db`) is replaced with an empty schema. Any in-flight deliveries currently in `pending` or `dm_accepted` state that have not yet been reconciled are lost.
- **Mitigation**: On ephemeral nodes, production deployments should configure a mounted persistent disk volume or connect to a managed external PostgreSQL instance.

---

### 4. Recipient DMs Disabled or Blocked (Terminal HTTP 400/401)
- **Condition**: A creator's follower has disabled DMs from non-followers or deleted their account. PseudoGram returns a `400 Bad Request` or `401 Unauthorized` response.
- **Impact**: The delivery is immediately marked as `failed` with the exact error details stored in `last_error`.
- **Mitigation**: The worker explicitly stops retrying terminal 400/401 errors to avoid wasting rate-limit capacity.
- **Remaining Risk**: The system cannot deliver DMs to users who have privacy restrictions; these count towards `failed` in `/stats`.

---

### 5. Prolonged Platform Status Outages During Reconciliation
- **Condition**: PseudoGram accepts a DM (`POST /v1/dm/send` returns 202 `dm_accepted`), but its internal status endpoint `GET /v1/dm/{dm_id}` returns persistent 500 errors or stays in `queued` state indefinitely.
- **Impact**: Deliveries remain in `dm_accepted` status, keeping `queued` > 0 in `/stats`.
- **Mitigation**: The reconciliation worker continuously polls `dm_accepted` records using unmetered status reads until a terminal `delivered` or `failed` state is confirmed.
