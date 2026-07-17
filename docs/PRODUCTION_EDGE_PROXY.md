# Production trusted edge proxy

Production uses two nginx layers with different responsibilities:

1. `edge` runs with host networking and owns public port 80. It can see the
   actual TCP peer, trusts forwarded addresses only from the documented Mikrus
   proxy range, and overwrites `X-Forwarded-For` with the sanitized client
   address.
2. `gateway` is bound only to `127.0.0.1:8080`. It performs hostname and path
   routing and passes the already-sanitized address to the Spring backends.

This separation is required because Docker's IPv6-to-IPv4 userland proxy makes
all traffic inside an ordinary bridge container appear to originate at the
Docker bridge gateway. Without the host-network edge, direct origin callers and
the Mikrus proxy are indistinguishable to the application gateway.

The trusted range comes from the Mikrus real-IP guidance:

<https://wiki.mikr.us/nginx_ograniczenie_dostepu_po_ip/>

## Verification

Run the regression check:

```bash
bash scripts/verify-edge-proxy.sh
```

It sends a deliberately forged `X-Forwarded-For` header through an untrusted
peer and verifies that the upstream receives the socket address instead of the
forged value.

Before changing the trusted range, capture the production source address at
the host boundary and confirm it against current Mikrus documentation. Never
add a broad trusted range merely to make a forwarded address appear correct.
