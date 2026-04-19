# ADR 006 — SSE over WebSocket for streaming

**Status:** Accepted
**Date:** 2026-04-18

## Context

The conversational coach UX (v0.4) streams stage results + master quotes +
coach commentary in real time as the 8-stage audit runs. The transport
options are Server-Sent Events (SSE) or WebSockets.

## Decision

Use SSE. FastAPI `StreamingResponse` with `text/event-stream` media type.
Client uses the browser-native `EventSource` API.

## Why

- **One-way flow**: client sends "start", server streams events. No client→server
  messages during an audit. SSE's unidirectional model fits exactly.
- **HTTP-native**: works through existing middleware (auth, logging, rate limit),
  survives most reverse proxies without config, plays nicely with corporate
  proxies if Ray ever wants to use it via Tailscale from an office.
- **Auto-reconnect is built in**: `EventSource` reconnects on drop by default
  (with `Last-Event-ID`).
- **Simpler server implementation**: a Python generator yielding bytes. No
  `asyncio` ceremony, no upgrade handshake, no ping/pong protocol.
- **Cache / CDN friendly**: if we ever need to replay past audits to the
  chat client, SSE streams are easier to proxy/cache.

## Consequences

**Positive:**
- ~30 lines of server code; client is 5 lines of `new EventSource(url)`
- Plays well with `curl -N` for debugging
- Graceful degradation (if JS disabled, HTML transcript still visible)

**Negative:**
- No binary payloads (must be UTF-8). Not an issue for us — everything is JSON.
- No client→server messages on the same connection. Not an issue — client
  posts follow-ups via separate `POST /chat/<id>/message` endpoint.
- Some old browsers / IE. Not relevant to Ray.

**Ruled out:**
- WebSocket-based bidirectional chat streaming (overengineered for our flow)
- Long-polling (uglier)

## Implementation notes

- Heartbeat `:keepalive\n\n` every 15s (prevents proxy idle timeout)
- `X-Accel-Buffering: no` header (disables nginx buffering if ever behind one)
- Client implements exponential backoff reconnect on `onerror`
