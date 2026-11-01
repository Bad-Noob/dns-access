#!/usr/bin/env bash

set -euo pipefail

mkdir -p /opt/dns-access
mkdir -p /opt/dns-access/app
mkdir -p /opt/dns-access/data

mkdir -p /opt/dns-admin
mkdir -p /opt/dns-admin/app

mkdir -p /etc/dns-access
mkdir -p /etc/dns-access/ssl

mkdir -p /var/log/dns-access
mkdir -p /var/log/dns-admin

chmod 700 /opt/dns-access
chmod 700 /opt/dns-access/data

chmod 700 /opt/dns-admin

chmod 700 /etc/dns-access
chmod 700 /etc/dns-access/ssl

chmod 750 /var/log/dns-access
chmod 750 /var/log/dns-admin

echo "Directories prepared successfully."
