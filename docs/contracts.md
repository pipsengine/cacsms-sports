# Contracts
All engine events require schema_version, event_id, correlation_id, emitted_at, source_engine and payload. Consumers must be idempotent. Qualification is centrally gated and must fail closed.
