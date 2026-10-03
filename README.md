# DNS Access

A self-hosted DNS access management system for Ubuntu servers.

## Features

* Interactive installation
* IPv4 and IPv6 support
* DNS access restricted to authorized client IP addresses
* Unique access links for users
* Automatic IP registration when an access link is opened
* DNS over HTTPS
* Recursive DNS resolution
* DNS caching and filtering
* HTTPS with Let's Encrypt
* Web-based administration panel
* User creation and management
* User expiration
* Enable and disable access
* IP address replacement
* SQLite database
* nftables-based DNS access control
* systemd service management
* Automatic certificate renewal
* Periodic access maintenance
* Dark and light administration interface

## Requirements

* Ubuntu
* Root access
* Public IPv4 address
* A domain pointing to the server
* A valid email address for TLS certificate registration

IPv6 is optional.

## Installation

Run:

```
curl -fsSL https://raw.githubusercontent.com/Bad-Noob/dns-access/main/install.sh | sudo bash
```

The installer will ask for:

* Server public IPv4
* Domain
* Let's Encrypt email
* Administrator username
* Administrator password
* IPv4 DNS support
* IPv6 DNS support
* DNS upstream configuration

The installer validates the configuration before continuing.

## Architecture

```
Client
  |
  | HTTPS
  v
Nginx
  |
  +---- /join/<token> ----> DNS Access Service
  |
  +---- /admin/ ----------> Admin Panel
  |
  +---- /dns-query -------> DNS HTTPS Service
                              |
                              v
                         DNS Resolver
```

DNS access is controlled by the client's public IP address.

Opening the user's access link registers the current public IP address and authorizes it for the user's remaining subscription period.

## Security

The system uses:

* HTTPS
* Let's Encrypt certificates
* IP-based DNS authorization
* nftables
* root-owned configuration files
* restricted local service bindings
* encrypted stored access links
* systemd service isolation
* SQLite database permissions

Never expose administrative configuration files or generated secrets publicly.

## Repository Structure

```
dns-access/
├── install.sh
├── dns-access/
│   ├── app.py
│   ├── requirements.txt
│   └── __init__.py
├── dns-admin/
│   ├── app.py
│   ├── requirements.txt
│   └── __init__.py
└── config/
    ├── AdGuardHome.service
    ├── AdGuardHome.yaml
    ├── certbot-renew.service
    ├── certbot-renew.timer
    ├── dns-access.env
    ├── dns-access.service
    ├── dns-admin.env
    ├── dns-admin.service
    ├── dns-maintenance.service
    ├── dns-maintenance.timer
    ├── dns-allow.conf
    ├── logrotate.conf
    ├── nginx.conf
    ├── nftables.conf
    ├── nftables.service
    ├── tmpfiles.conf
    ├── unbound.conf
    └── unbound.service
```

## License

Use and modify this project according to the license included with the repository.
