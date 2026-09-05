#!/usr/bin/env bash
# Desinstalador do Aviso Broadcaster (HOTNET) para Debian/Ubuntu.
# Remove o serviço systemd, os arquivos em /opt/aviso-broadcaster
# (incluindo config.json e service-account.json) e o usuário de sistema.
# Rode como root: ./uninstall.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "Execute este script como root (./uninstall.sh)." >&2
    exit 1
fi

INSTALL_DIR="/opt/aviso-broadcaster"
SERVICE_USER="aviso-broadcaster"
SERVICE_FILE="/etc/systemd/system/aviso-broadcaster.service"
POLLER_SERVICE_FILE="/etc/systemd/system/controllr-poller.service"
POLLER_TIMER_FILE="/etc/systemd/system/controllr-poller.timer"

echo "Isso vai remover:"
echo "  - o serviço systemd aviso-broadcaster"
echo "  - o timer/serviço do poller (controllr-poller), se instalado"
echo "  - a pasta $INSTALL_DIR (config.json, service-account.json e"
echo "    controllr_config.json incluídos)"
echo "  - o usuário de sistema $SERVICE_USER"
echo ""
read -rp "Confirma a desinstalação completa? [s/N] " CONFIRMA
if [[ ! "$CONFIRMA" =~ ^[sS]$ ]]; then
    echo "Cancelado."
    exit 0
fi

if systemctl list-unit-files | grep -q "^aviso-broadcaster.service"; then
    echo "== Parando e desabilitando o serviço =="
    systemctl stop aviso-broadcaster 2>/dev/null || true
    systemctl disable aviso-broadcaster 2>/dev/null || true
fi

if [[ -f "$SERVICE_FILE" ]]; then
    echo "== Removendo unidade systemd =="
    rm -f "$SERVICE_FILE"
    systemctl daemon-reload
fi

if systemctl list-unit-files | grep -q "^controllr-poller.timer"; then
    echo "== Parando e desabilitando o poller =="
    systemctl stop controllr-poller.timer 2>/dev/null || true
    systemctl disable controllr-poller.timer 2>/dev/null || true
fi

if [[ -f "$POLLER_SERVICE_FILE" || -f "$POLLER_TIMER_FILE" ]]; then
    echo "== Removendo unidades systemd do poller =="
    rm -f "$POLLER_SERVICE_FILE" "$POLLER_TIMER_FILE"
    systemctl daemon-reload
fi

if [[ -d "$INSTALL_DIR" ]]; then
    echo "== Removendo $INSTALL_DIR =="
    rm -rf "$INSTALL_DIR"
fi

if id "$SERVICE_USER" &>/dev/null; then
    echo "== Removendo usuário de sistema $SERVICE_USER =="
    userdel --remove "$SERVICE_USER" 2>/dev/null || userdel "$SERVICE_USER"
fi

echo ""
echo "Desinstalação concluída."
