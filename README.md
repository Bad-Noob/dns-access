# DNS Access

A self-hosted DNS access management system for Ubuntu servers.

DNS Access provides subscription-based DNS access using client IP authorization, a web-based administrator panel, nftables, AdGuard Home, and Unbound.

## Features

- Interactive Ubuntu installation
- IPv4 and optional IPv6 support
- Individual user access links
- Random access tokens
- Automatic client source IP registration
- Automatic IP replacement after network changes
- Subscription expiration and renewal
- User creation, activation, deactivation, and deletion
- Web-based administrator panel
- SQLite database
- Encrypted storage of recoverable access links
- nftables DNS access control
- AdGuard Home DNS filtering and caching
- Unbound recursive DNS resolution
- Automated maintenance and health checks
- systemd services and timers
- Log rotation configuration

## Architecture

| Component | Purpose | Default Port |
|---|---|---|
| DNS Access | Token validation and client IP registration | TCP 8787 |
| DNS Admin | User and subscription management | TCP 8790 |
| AdGuard Home | DNS filtering and caching | UDP/TCP 53 |
| Unbound | Recursive DNS resolver | UDP/TCP 5353 |
| AdGuard Home UI | Local administration | TCP 8081 |

DNS query flow:

1. The client sends a DNS query to port 53.
2. nftables checks the client's source IP address.
3. Authorized requests reach AdGuard Home.
4. AdGuard Home forwards queries to Unbound at 127.0.0.1:5353.
5. Unbound performs recursive DNS resolution.

Unbound uses root hints and DNSSEC trust-anchor configuration. It does not use an external recursive DNS forwarder.

## Requirements

- Ubuntu server
- Root or sudo access
- Public IPv4 address
- Public IPv6 address if IPv6 is enabled
- Internet connectivity during installation
- Interactive terminal access

The installer requires an interactive terminal.

## Installation

Run the installer as root:

    curl -fsSL https://raw.githubusercontent.com/Bad-Noob/dns-access/main/install.sh | sudo bash

The installer requests:

- Public IPv4 address
- Administrator username
- Administrator password
- IPv4 enablement
- Optional IPv6 enablement and public IPv6 address
- Installation confirmation

The administrator password must contain at least 12 characters.

The installer installs system packages, downloads the project and AdGuard Home, creates Python virtual environments, generates secrets, configures Unbound and nftables, installs systemd services, starts the services, and runs initial maintenance and health checks.

## Optional DNS over HTTPS (DoH)

The installer can optionally configure DNS over HTTPS (DoH) on TCP port 443.

Requirements:

- A domain name with an A record pointing to the server's public IPv4 address.
- Inbound TCP port 80 reachable and available to Certbot during Let's Encrypt HTTP-01 certificate issuance and renewal.
- Inbound TCP port 443 reachable for DoH clients.
- Any configured AAAA record must point to a working IPv6 address on this server. Remove an incorrect AAAA record before installation.

During installation, enable the optional DoH feature and provide the domain name. A Let's Encrypt email address is recommended for certificate expiry notifications.

The installer obtains a certificate with Certbot, configures AdGuard Home to serve DoH at `https://DOMAIN/dns-query`, and installs a certificate renewal deploy hook that restarts AdGuard Home.

This option enables DoH only. DNS-over-TLS and DNS-over-QUIC are not enabled by this option.

DoH encrypts DNS requests between the client and the server. It does not hide the destination IP address or guarantee that network filtering or blocking will be bypassed.

## User Access Links

Access links use this format:

    http://SERVER-IP:8787/join/TOKEN

When a user opens a valid link:

- The token is validated against its stored hash.
- Disabled and expired accounts are rejected.
- The connecting client's source IP address is detected.
- The IP address is associated with the user.
- The authorized address is added to the appropriate nftables set.
- A previous address is removed when the user reconnects from another network.

IPv4 and IPv6 are supported when enabled.

Access links are private credentials. Share them only with their intended users.

## DNS Access Control

nftables maintains two dynamic address sets:

- dns4: authorized IPv4 addresses
- dns6: authorized IPv6 addresses

Authorized clients can use both UDP and TCP DNS.

Unauthorized DNS traffic to port 53 is dropped. Local loopback DNS traffic is allowed.

Authorization entries use timeouts based on subscription expiration. The maintenance service refreshes active entries and removes expired or disabled users.

These rules control DNS traffic. They are not a general-purpose firewall policy for all server ports.

## DNS Resolution

### AdGuard Home

AdGuard Home listens on port 53 and provides DNS filtering and caching.

Its configuration is generated during installation. Its administrative interface is configured for local access on port 8081.

### Unbound

Unbound listens on 127.0.0.1:5353 and performs recursive DNS resolution using root hints and DNSSEC trust-anchor configuration.

AdGuard Home forwards DNS queries to Unbound locally.

## Administrator Panel

Open the panel at:

    http://SERVER-IP:8790/admin/

The panel provides:

- Administrator authentication
- User creation with configurable duration
- User list and subscription status
- Expiration information
- Registered IPv4 and IPv6 addresses
- Subscription renewal by 30 days
- Enable and disable controls
- User deletion
- Access link retrieval
- Total, active, disabled, and expired user statistics

New users can be created with a duration from 1 to 3650 days.

## Services and Maintenance

The installer configures these services:

| Service | Purpose |
|---|---|
| dns-access.service | User access endpoint |
| dns-admin.service | Administrator panel |
| AdGuardHome.service | DNS filtering |
| unbound.service | Recursive DNS |
| nftables.service | DNS firewall rules |
| dns-maintenance.service | Subscription and firewall maintenance |
| healthcheck.service | Service health checks |

Automatic timers:

- dns-maintenance.timer
- healthcheck.timer
- dns-access-logrotate.timer

## Configuration and Data

Important runtime paths:

| Path | Description |
|---|---|
| /opt/dns-access/ | DNS Access application |
| /opt/dns-access/data/users.db | SQLite database |
| /opt/dns-admin/ | Administrator application |
| /opt/AdGuardHome/ | AdGuard Home installation |
| /etc/dns-access.conf | DNS Access environment |
| /etc/dns-admin.env | Administrator credentials and secrets |
| /etc/dns-access/ | DNS Access configuration |
| /etc/unbound/ | Unbound configuration |

Passwords, encryption keys, database contents, and server-specific secrets must not be committed to the repository.

## Network Ports

| Port | Protocol | Service |
|---|---|---|
| 53 | UDP/TCP | DNS |
| 80 | TCP | Temporary Let's Encrypt HTTP-01 challenge and certificate renewal |
| 443 | TCP | Optional DNS over HTTPS (DoH) |
| 8787 | TCP | User access endpoint |
| 8790 | TCP | Administrator panel |
| 5353 | UDP/TCP | Local Unbound resolver |
| 8081 | TCP | Local AdGuard Home interface |

The access endpoint and administrator panel bind to 0.0.0.0 by default. Restrict administrator panel access using a suitable firewall or secure reverse proxy.

Unbound and the AdGuard Home administrative interface are intended for local access.

## Security

- DNS access is restricted using nftables IP authorization.
- Access tokens are stored as SHA-256 hashes.
- Recoverable access links are encrypted using Fernet when the encryption key is available.
- Administrator credentials and application secrets are stored outside the repository.
- Sensitive configuration files receive restrictive permissions.
- Disabled and expired users lose DNS authorization through maintenance.
- Deleting a user removes associated authorized IP addresses.

The default DNS Access user access endpoint and DNS Access administrator panel use HTTP, not HTTPS. Optional DoH configuration enables AdGuard Home's HTTPS listener on TCP port 443. This listener serves both DNS-over-HTTPS and the AdGuard Home web interface over HTTPS. It does not enable HTTPS for the separate DNS Access user access endpoint or DNS Access administrator panel.

For production use, restrict access to administrative interfaces. Configure HTTPS for the DNS Access web interfaces separately if required. Keep TCP port 80 reachable and available to Certbot during HTTP-01 certificate issuance and renewal when optional DoH is enabled.

## Health Checks

The health-check script checks service status, DNS listeners, application ports, nftables configuration, and Unbound configuration.

Run it manually:

    sudo /opt/dns-access/healthcheck.sh

## Repository Structure

    dns-access/
    ├── dns-access/
    │   ├── app.py
    │   ├── maintenance.py
    │   ├── healthcheck.sh
    │   ├── requirements.txt
    │   ├── Makefile
    │   └── __init__.py
    ├── dns-admin/
    │   ├── app.py
    │   ├── requirements.txt
    │   └── __init__.py
    ├── config/
    │   ├── AdGuardHome.service
    │   ├── AdGuardHome.yaml
    │   ├── defaults.conf
    │   ├── dns-access.conf
    │   ├── dns-access.env
    │   ├── dns-access.service
    │   ├── dns-admin.env
    │   ├── dns-admin.service
    │   ├── dns-maintenance.service
    │   ├── dns-maintenance.timer
    │   ├── dns-access-logrotate
    │   ├── dns-access-logrotate.service
    │   ├── dns-access-logrotate.timer
    │   ├── healthcheck.service
    │   ├── healthcheck.timer
    │   ├── limits.conf
    │   ├── logrotate.conf
    │   ├── nftables.conf
    │   ├── nftables.service
    │   ├── sysctl.conf
    │   ├── tmpfiles.conf
    │   ├── unbound.conf
    │   ├── unbound.service
    │   └── README.md
    ├── scripts/
    ├── .gitignore
    ├── install.sh
    ├── LICENSE
    ├── README.md
    └── VERSION

## License

This project is licensed under the MIT License. See LICENSE.
