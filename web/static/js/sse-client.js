/**
 * Moatlens SSE client — handles reconnect with exponential backoff,
 * heartbeat tracking, and typed event dispatch.
 *
 * Usage:
 *   const client = new MoatlensSSE({
 *     url: '/chat/abc123/stream',
 *     onEvent: (kind, payload) => { ... },
 *     onReconnecting: (attempt) => { ... },
 *     onFatal: (err) => { ... },
 *   });
 *   client.start();
 *   // ... later: client.stop();
 */
(function (global) {
    'use strict';

    class MoatlensSSE {
        constructor(opts) {
            this.url = opts.url;
            this.onEvent = opts.onEvent || (() => {});
            this.onReconnecting = opts.onReconnecting || (() => {});
            this.onConnected = opts.onConnected || (() => {});
            this.onFatal = opts.onFatal || (() => {});
            this.maxRetries = opts.maxRetries != null ? opts.maxRetries : 5;
            this.heartbeatTimeoutMs = opts.heartbeatTimeoutMs || 45000;  // 3x server's 15s keepalive

            this.es = null;
            this.retries = 0;
            this.closed = false;
            this.lastEventAt = 0;
            this.heartbeatTimer = null;
        }

        start() {
            this.closed = false;
            this._connect();
        }

        stop() {
            this.closed = true;
            this._clearHeartbeat();
            if (this.es) {
                this.es.close();
                this.es = null;
            }
        }

        _connect() {
            if (this.closed) return;
            try {
                this.es = new EventSource(this.url);
            } catch (e) {
                this.onFatal(e);
                return;
            }

            this.es.onopen = () => {
                this.retries = 0;
                this.lastEventAt = Date.now();
                this._armHeartbeat();
                this.onConnected();
            };

            this.es.onmessage = (ev) => {
                this.lastEventAt = Date.now();
                this._armHeartbeat();
                let data;
                try {
                    data = JSON.parse(ev.data);
                } catch (err) {
                    console.warn('[SSE] malformed JSON payload, dropping', ev.data);
                    return;
                }
                try {
                    this.onEvent(data.kind || 'unknown', data);
                } catch (err) {
                    console.error('[SSE] handler threw', err);
                }

                // If the server sends a terminal event, close cleanly.
                if (data.kind === 'final' || data.kind === 'already_complete' || data.kind === 'error') {
                    this.closed = true;
                    this._clearHeartbeat();
                    this.es.close();
                }
            };

            this.es.onerror = () => {
                // Browser will auto-retry, but we want to control backoff.
                if (this.es && this.es.readyState === EventSource.CLOSED) {
                    this._scheduleReconnect();
                }
            };
        }

        _scheduleReconnect() {
            if (this.closed) return;
            this.retries += 1;
            if (this.retries > this.maxRetries) {
                this.onFatal(new Error('Exceeded max reconnect attempts'));
                this.stop();
                return;
            }
            // Exponential backoff with jitter: 1s, 2s, 4s, 8s, 16s capped at 30s
            const delay = Math.min(30000, 1000 * Math.pow(2, this.retries - 1))
                        + Math.random() * 500;
            this.onReconnecting(this.retries);
            setTimeout(() => this._connect(), delay);
        }

        _armHeartbeat() {
            this._clearHeartbeat();
            this.heartbeatTimer = setTimeout(() => {
                // No message for heartbeatTimeoutMs → assume dead, force reconnect
                if (this.es && this.es.readyState !== EventSource.CLOSED) {
                    this.es.close();
                }
                this._scheduleReconnect();
            }, this.heartbeatTimeoutMs);
        }

        _clearHeartbeat() {
            if (this.heartbeatTimer) {
                clearTimeout(this.heartbeatTimer);
                this.heartbeatTimer = null;
            }
        }
    }

    global.MoatlensSSE = MoatlensSSE;
})(window);
