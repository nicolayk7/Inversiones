-- Runs once, on first container start (docker-entrypoint-initdb.d).
-- Phase 0 only enables extensions — business tables land per-engine starting Phase 1.

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS vector;
