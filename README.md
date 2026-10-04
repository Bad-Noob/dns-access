# DNS Access

A self-hosted DNS access management system for Ubuntu servers.

## Features

- Interactive one-command installation
- IPv4 support
- Optional IPv6 support
- Per-user access links
- Automatic public IP registration
- Automatic IP replacement when a user reconnects
- DNS access restricted by authorized IP addresses
- DNS over HTTPS
- Recursive DNS resolution
- Optional DNS over TLS upstreams
- Optional plain DNS upstreams
- DNS caching
- DNS filtering
- Let's Encrypt TLS certificates
- Web-based administrator panel
- SQLite database
- User expiration
- User renewal
- Enable and disable access
- nftables-based DNS protection
- systemd service management
- Automatic certificate renewal
- Periodic maintenance
- Health checks

## Requirements

- Ubuntu
- Root access
- Public IPv4 address
- A domain pointing to the server
- A valid email address for Let's Encrypt
- IPv6 is optional

## Installation

Run:

    curl -fsSL https://raw.githubusercontent.com/Bad-Noob/dns-access/main/install.sh | sudo bash

The installer interactively asks for:

- Public IPv4 address
- Domain name
- Let's Encrypt email
- Administrator username
- Administrator password
- IPv4 support
- IPv6 support
- DNS upstream mode
- DNS upstream addresses when required

The installer then:

1. Installs required system packages.
2. Downloads the project.
3. Creates application directories.
4. Creates isolated Python environments.
5. Generates server secrets.
6. Configures the DNS resolver.
7. Installs the DNS filtering service.
8. Configures nftables.
9. Obtains a Let's Encrypt certificate.
10. Configures Nginx.
11. Starts the required services.
12. Runs health checks.

## DNS Modes

The installer supports three resolver modes.

### Recursive

The server performs recursive DNS resolution directly.

### DNS over TLS

The resolver forwards DNS queries to configured TLS upstream servers.

### Plain DNS

The resolver forwards DNS queries to configured DNS servers without TLS.

## Access Links

Each user receives a unique access link:

    https://example.com/join/<token>

When the user opens the link:

1. The server validates the token.
2. The current public IP address is detected.
3. The IP address is associated with the user.
4. DNS access is authorized for the remaining subscription period.
5. The previous IP address is removed when necessary.

Opening the same link from a new network replaces the previous address.

## DNS

Normal DNS service uses port 53.

DNS access is protected by nftables and only authorized client addresses are permitted.

DNS over HTTPS is available through:

    https://example.com/dns-query

The internal HTTPS DNS service is not intended to be exposed directly to the Internet.

## Administrator Panel

The administrator panel is available at:

    https://example.com/admin/

The panel provides:

- Administrator authentication
- User creation
- Subscription duration
- User listing
- Expiration information
- IPv4 and IPv6 information
- User renewal
- Enable and disable controls
- User deletion
- Access link retrieval
- Basic statistics

## Security

The system uses:

- HTTPS
- Let's Encrypt certificates
- IP-based DNS authorization
- nftables
- Restricted local service bindings
- Root-owned configuration
- SQLite
- Encrypted stored access links
- Generated application secrets
- systemd service isolation
- Automatic maintenance

Generated passwords, keys, and certificates are stored outside the repository.

## Repository Structure

    dns-access/
    ├── install.sh
    ├── VERSION
    ├── README.md
    ├── LICENSE
    │
    ├── dns-access/
    │   ├── app.py
    │   ├── maintenance.py
    │   ├── healthcheck.sh
    │   ├── requirements.txt
    │   ├── Makefile
    │   └── __init__.py
    │
    ├── dns-admin/
    │   ├── app.py
    │   ├── requirements.txt
    │   └── __init__.py
    │
    ├── scripts/
    │   ├── prepare-directories.sh
    │   ├── check-requirements.sh
    │   ├── generate-secrets.sh
    │   ├── check-dns.sh
    │   ├── test-nginx.sh
    │   ├── test-unbound.sh
    │   ├── test-nftables.sh
    │   ├── test-services.sh
    │   ├── run-tests.sh
    │   ├── version.sh
    │   └── check-project.sh
    │
    └── config/
        ├── AdGuardHome.service
        ├── AdGuardHome.yaml
        ├── certbot-renew.service
        ├── certbot-renew.timer
        ├── dns-access.conf
        ├── dns-access.env
        ├── dns-access.service
        ├── dns-access-security.conf
        ├── dns-admin.env
        ├── dns-admin.service
        ├── dns-allow.conf
        ├── dns-maintenance.service
        ├── dns-maintenance.timer
        ├── healthcheck.service
        ├── healthcheck.timer
        ├── nginx.conf
        ├── nftables.conf
        ├── nftables.service
        ├── tmpfiles.conf
        ├── unbound.conf
        ├── unbound-forwarders.conf
        ├── unbound-forwarders-direct.conf
        └── unbound.service

## License

This project is licensed under the MIT License.
