# A redirect can pull the fetcher onto an internal host

`fetch` in `src/fetcher/client.py` is documented to never fetch an
internal or private host, neither directly nor through a redirect:
such a URL is refused with `ValueError`.

Today, redirects are followed to any host, so a public URL can redirect
the fetcher to `localhost` or to a cloud metadata address
(`169.254.169.254`). The repository's own test suite only fetches
public hosts, so it stays green.

Locate the SSRF and close it: before every fetch (the initial URL and
every redirect target), refuse internal or private hosts with
`ValueError`. Internal means `localhost` (and subdomains of it) and
private or link-local IP addresses (`10/8`, `172.16/12`, `192.168/16`,
`127/8`, `169.254/16`, `::1`). Public hosts must keep working, and
redirects between public hosts must still be followed.

## What to check

- A public URL redirecting to `localhost` is refused.
- A public URL redirecting to `169.254.169.254` is refused.
- A direct fetch of a private IP is refused.
- Public fetches and public-to-public redirects still work, and the
  redirect limit still applies.

## Boundaries

- Do not change the public API of the `fetcher` package.
- Do not modify the repository test suite under `tests/`.
- No network access: the transport stays injected.
- The repository's own test suite has to stay green after your change.
