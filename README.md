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
- Recursive DNS resolution
- DNS caching
- DNS filtering
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
- IPv6 is optional

## Installation

Run:

    curl -fsSL https://raw.githubusercontent.com/Bad-Noob/dns-access/main/install.sh | sudo bash

The installer interactively asks for:

- Public IPv4 address
- Administrator username
- Administrator password
- IPv4 support
- IPv6 support

The installer then:

1. Installs required system packages.
2. Downloads the project.
3. Creates application directories.
4. Creates isolated Python environments.
5. Generates server secrets.
6. Configures the DNS resolver.
7. Installs the DNS filtering service.
8. Configures nftables.
9. Configures the DNS access and administrator services.
10. Starts the required services.
11. Runs health checks.

## DNS Resolution

Unbound performs recursive DNS resolution directly. No external DNS
forwarders or upstream mode selection are configured.

## Access Links

Each user receives a unique access link:

    http://SERVER-IP:8787/join/<token>

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

DNS over HTTPS is not provided. DNS clients connect directly to the server using DNS on port 53.

## Administrator Panel

The administrator panel is available at:

    http://SERVER-IP:8790/admin/

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
        ├── dns-access.conf
        ├── dns-access.env
        ├── dns-access.service
        ├── dns-admin.env
        ├── dns-admin.service
        ├── dns-maintenance.service
        ├── dns-maintenance.timer
        ├── healthcheck.service
        ├── healthcheck.timer
        ├── nftables.conf
        ├── nftables.service
        ├── tmpfiles.conf
        ├── unbound.conf
        └── unbound.service

## License

This project is licensed under the MIT License.
