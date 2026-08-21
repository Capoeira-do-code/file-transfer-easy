package tunnel

import (
	"context"
	"errors"
	"net"
	"net/url"
	"time"
)

// Cloudflare creates the DNS record for a quick tunnel *after* cloudflared
// prints the URL — measured at around 14 seconds. That gap matters a lot,
// because trycloudflare.com has no wildcard record and its SOA sets a negative
// cache TTL of 1800 seconds: whoever looks the name up too early caches
// NXDOMAIN for half an hour and sees a dead link the whole time.
//
// So the app must not hand the link over until the name really resolves. The
// wait below deliberately queries public resolvers directly instead of the
// system one, so that our own polling cannot be what poisons the user's cache.

// publicResolvers are queried directly while waiting for the record to appear.
var publicResolvers = []string{"1.1.1.1:53", "8.8.8.8:53"}

const (
	resolvePollInterval = 1 * time.Second
	resolveTimeout      = 90 * time.Second
	// blindWait is how long to wait before going ahead anyway when the public
	// resolvers cannot be reached at all, e.g. on a network that blocks
	// outbound DNS. It is comfortably longer than the delay seen in practice.
	blindWait = 25 * time.Second
)

// newDirectResolver builds a resolver that talks to a public DNS server rather
// than the machine's configured one.
func newDirectResolver(server string) *net.Resolver {
	return &net.Resolver{
		PreferGo: true,
		Dial: func(ctx context.Context, network, _ string) (net.Conn, error) {
			dialer := net.Dialer{Timeout: 5 * time.Second}
			return dialer.DialContext(ctx, network, server)
		},
	}
}

// WaitUntilResolvable blocks until the host in rawURL resolves publicly, or the
// timeout expires. It reports whether the name was actually seen to resolve.
//
// A false return is not necessarily fatal: the caller may still publish the
// link, it just cannot promise the record is live yet.
func WaitUntilResolvable(ctx context.Context, rawURL string, log Logf) bool {
	parsed, err := url.Parse(rawURL)
	if err != nil {
		return false
	}
	host := parsed.Hostname()
	if host == "" {
		return false
	}

	resolvers := make([]*net.Resolver, 0, len(publicResolvers))
	for _, server := range publicResolvers {
		resolvers = append(resolvers, newDirectResolver(server))
	}

	if log != nil {
		log("info", "Esperando a que el enlace esté publicado en el DNS…")
	}

	deadline := time.After(resolveTimeout)
	blind := time.After(blindWait)
	ticker := time.NewTicker(resolvePollInterval)
	defer ticker.Stop()

	// reachable tracks whether any public resolver ever answered us at all, so
	// that a blocked network can be told apart from a record that is simply not
	// there yet.
	var reachable bool
	started := time.Now()

	for {
		for _, resolver := range resolvers {
			lookup, cancel := context.WithTimeout(ctx, 4*time.Second)
			addrs, err := resolver.LookupHost(lookup, host)
			cancel()

			if err == nil && len(addrs) > 0 {
				if log != nil {
					log("info", "El enlace ya resuelve (%s)", time.Since(started).Round(time.Second))
				}
				return true
			}
			var dnsErr *net.DNSError
			if errors.As(err, &dnsErr) && dnsErr.IsNotFound {
				// A clean "not found" means the resolver answered: the record
				// just has not been published yet.
				reachable = true
			}
		}

		select {
		case <-ctx.Done():
			return false

		case <-blind:
			if !reachable {
				if log != nil {
					log("warn", "No se pudo consultar el DNS público; se publica el enlace de todos modos")
				}
				return false
			}

		case <-deadline:
			if log != nil {
				log("warn", "El DNS del enlace tarda más de lo normal en publicarse")
			}
			return false

		case <-ticker.C:
		}
	}
}
