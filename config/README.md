# Service Configuration

This directory contains the service configuration templates used by the installer.

The installer generates the final runtime configuration under:

- `/etc/dns-access/`
- `/etc/dns-access.conf`
- `/etc/dns-admin.env`
- `/etc/unbound/`

Configuration files containing passwords, encryption keys, certificates, or other server-specific secrets are generated during installation and are not stored in the repository.
