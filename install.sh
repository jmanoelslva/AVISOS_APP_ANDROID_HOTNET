#!/usr/bin/env bash
# Instalador do Aviso Broadcaster (HOTNET) para Debian/Ubuntu.
# Rode como root: ./install.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "Execute este script como root (./install.sh)." >&2
    exit 1
fi

INSTALL_DIR="/opt/aviso-broadcaster"
SERVICE_USER="aviso-broadcaster"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "== Instalando dependências do sistema =="
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip

echo "== Criando usuário de sistema (sem shell/login) =="
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd --system --create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi

echo "== Copiando arquivos para $INSTALL_DIR =="
mkdir -p "$INSTALL_DIR"
cp -r "$SCRIPT_DIR"/app.py "$SCRIPT_DIR"/config_store.py "$SCRIPT_DIR"/security.py \
    "$SCRIPT_DIR"/fcm_sender.py "$SCRIPT_DIR"/templates "$SCRIPT_DIR"/static "$SCRIPT_DIR"/requirements.txt \
    "$SCRIPT_DIR"/gunicorn.conf.py \
    "$SCRIPT_DIR"/controllr_client.py "$SCRIPT_DIR"/controllr_config.py \
    "$SCRIPT_DIR"/poller.py "$SCRIPT_DIR"/state_store.py \
    "$SCRIPT_DIR"/access_log.py "$SCRIPT_DIR"/painel_info.py "$SCRIPT_DIR"/lembretes.py "$SCRIPT_DIR"/envios_log.py "$SCRIPT_DIR"/permissoes.py \
    "$INSTALL_DIR"/

if [[ -f "$SCRIPT_DIR/service-account.json" ]]; then
    cp "$SCRIPT_DIR/service-account.json" "$INSTALL_DIR"/
else
    echo ""
    echo "AVISO: service-account.json não encontrado nesta pasta."
    echo "Gere em Firebase Console > Configurações do projeto > Contas de"
    echo "serviço > Gerar nova chave privada, e coloque em:"
    echo "  $INSTALL_DIR/service-account.json"
    echo "Sem esse arquivo, o painel abre normalmente, mas o envio de avisos falha."
    echo ""
fi

echo "== Criando ambiente virtual Python =="
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"

echo ""
echo "== Configuração inicial do painel =="

read -rp "Usuário de acesso ao painel: " ADMIN_USER
while [[ -z "$ADMIN_USER" ]]; do
    read -rp "Usuário não pode ser vazio. Usuário de acesso: " ADMIN_USER
done

validar_senha() {
    local senha="$1"
    [[ ${#senha} -ge 8 && ${#senha} -le 128 ]] || return 1
    [[ "$senha" =~ [A-Z] ]] || return 1
    [[ "$senha" =~ [a-z] ]] || return 1
    [[ "$senha" =~ [0-9] ]] || return 1
    [[ "$senha" =~ [^A-Za-z0-9] ]] || return 1
    return 0
}

while true; do
    echo "Senha: 8 a 128 caracteres, com uma letra maiúscula (A-Z), uma minúscula (a-z),"
    echo "um número (0-9) e um símbolo (ex.: ! @ # \$ % & * - _ .)."
    read -rsp "Senha: " ADMIN_PASS
    echo
    read -rsp "Confirme a senha: " ADMIN_PASS_CONFIRM
    echo
    if [[ "$ADMIN_PASS" != "$ADMIN_PASS_CONFIRM" ]]; then
        echo "As senhas não coincidem. Tente de novo."
        continue
    fi
    if validar_senha "$ADMIN_PASS"; then
        break
    else
        echo "Senha não atende aos requisitos mínimos. Tente de novo."
    fi
done

read -rp "Porta do painel web [8765]: " ADMIN_PORT
ADMIN_PORT="${ADMIN_PORT:-8765}"

echo ""
echo "Domínio (opcional). Com domínio, o painel fica em https://SEU_DOMINIO, com"
echo "certificado Let's Encrypt emitido e renovado automaticamente, e a porta acima"
echo "passa a ser só interna. O domínio precisa já apontar (A/AAAA) para este"
echo "servidor, com as portas 80 e 443 liberadas. Sem domínio: http://IP:PORTA."
read -rp "Domínio do painel (Enter para usar só o IP): " DOMINIO
DOMINIO="${DOMINIO,,}"
EMAIL_LE=""
if [[ -n "$DOMINIO" ]]; then
    read -rp "E-mail para avisos do Let's Encrypt (recomendado; Enter para pular): " EMAIL_LE
fi

echo "== Gravando configuração inicial =="
"$INSTALL_DIR/venv/bin/python" - "$INSTALL_DIR" "$ADMIN_USER" "$ADMIN_PASS" "$ADMIN_PORT" <<'PYEOF'
import sys

sys.path.insert(0, sys.argv[1])
import config_store
from werkzeug.security import generate_password_hash

cfg = config_store.carregar()
cfg["usuarios"] = [{
    "username": sys.argv[2],
    "password_hash": generate_password_hash(sys.argv[3]),
    "grupo": "Administrador",
    "is_admin": True,
    "ativo": True,
}]
cfg["port"] = int(sys.argv[4])
config_store.salvar(cfg)
print("Configuração inicial salva.")
PYEOF

unset ADMIN_PASS ADMIN_PASS_CONFIRM

chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
chmod 600 "$INSTALL_DIR/config.json" 2>/dev/null || true

echo "== Instalando serviço systemd =="
cp "$SCRIPT_DIR/aviso-broadcaster.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable aviso-broadcaster
systemctl restart aviso-broadcaster

DOMINIO_OK=0
if [[ -n "$DOMINIO" ]]; then
    echo "== Domínio e HTTPS (Let's Encrypt) =="
    if INSTALL_DIR="$INSTALL_DIR" "$SCRIPT_DIR/configurar-dominio.sh" "$DOMINIO" ${EMAIL_LE:+"$EMAIL_LE"}; then
        DOMINIO_OK=1
    else
        echo ""
        echo "AVISO: não foi possível configurar $DOMINIO (veja o erro acima)."
        echo "O painel continua acessível por IP e porta. Depois de corrigir"
        echo "(DNS, portas 80/443), rode:"
        echo "  cd $SCRIPT_DIR && ./configurar-dominio.sh $DOMINIO $EMAIL_LE"
    fi
fi

echo ""
echo "== Poller de eventos por conta (pagamento confirmado, chamado"
echo "   atualizado, fatura atrasada) — opcional =="
echo "Consulta o Controllr periodicamente (a cada 1 hora) como um usuário"
echo "ADMIN dedicado, só leitura, numa porta diferente da área de cliente"
echo "(8080/8081/8443, conforme configurado no seu Controllr). Não altera"
echo "nada no Controllr, só lê. Detalhes: README.md, seção 9."
echo ""
POLLER_INSTALADO=0
read -rp "Configurar agora? [s/N]: " CONFIGURAR_POLLER
if [[ "$CONFIGURAR_POLLER" =~ ^[Ss]$ ]]; then
    read -rp "URL base da área ADMINISTRATIVA do Controllr (ex: https://controllr.seudominio.com.br:8443/): " CTL_URL
    while [[ -z "$CTL_URL" ]]; do
        read -rp "Não pode ser vazio. URL: " CTL_URL
    done
    read -rp "Usuário admin dedicado (só leitura) do Controllr: " CTL_USER
    while [[ -z "$CTL_USER" ]]; do
        read -rp "Não pode ser vazio. Usuário: " CTL_USER
    done
    read -rsp "Senha desse usuário: " CTL_PASS
    echo

    "$INSTALL_DIR/venv/bin/python" - "$INSTALL_DIR" "$CTL_URL" "$CTL_USER" "$CTL_PASS" <<'PYEOF'
import json
import sys

with open(f"{sys.argv[1]}/controllr_config.json", "w", encoding="utf-8") as f:
    json.dump(
        {"base_url": sys.argv[2], "usuario": sys.argv[3], "senha": sys.argv[4]},
        f, indent=2, ensure_ascii=False,
    )
PYEOF
    unset CTL_PASS
    chown "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/controllr_config.json"
    chmod 600 "$INSTALL_DIR/controllr_config.json"

    echo "== Rodando o poller pela primeira vez (grava a baseline; não notifica ninguém nessa execução) =="
    if (cd "$INSTALL_DIR" && "$INSTALL_DIR/venv/bin/python" poller.py); then
        chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
        chmod 600 "$INSTALL_DIR/poller_state.json" 2>/dev/null || true
        cp "$SCRIPT_DIR/controllr-poller.service" "$SCRIPT_DIR/controllr-poller.timer" /etc/systemd/system/
        systemctl daemon-reload
        systemctl enable --now controllr-poller.timer
        POLLER_INSTALADO=1
        echo "Poller instalado e rodando (controllr-poller.timer, a cada 1 hora)."
    else
        echo ""
        echo "AVISO: a primeira execução do poller falhou (veja o erro acima —"
        echo "provavelmente URL/usuário/senha do Controllr errados). O timer NÃO"
        echo "foi instalado de propósito. Corrija $INSTALL_DIR/controllr_config.json"
        echo "e rode manualmente depois:"
        echo "  chown -R $SERVICE_USER:$SERVICE_USER $INSTALL_DIR"
        echo "  su -s /bin/bash $SERVICE_USER -c 'cd $INSTALL_DIR && venv/bin/python poller.py'"
        echo "Confirme \"baseline gravada\" na aba Logs do painel antes de instalar:"
        echo "  cp $SCRIPT_DIR/controllr-poller.service $SCRIPT_DIR/controllr-poller.timer /etc/systemd/system/"
        echo "  systemctl daemon-reload && systemctl enable --now controllr-poller.timer"
    fi
else
    echo "Pulado — veja a seção 9 do README.md pra configurar depois."
fi

IP_LOCAL="$(hostname -I 2>/dev/null | awk '{print $1}')"

echo ""
echo "=================================================="
echo "Instalação concluída!"
if [[ "$DOMINIO_OK" -eq 1 ]]; then
    echo "Painel disponível em: https://$DOMINIO (certificado com renovação automática)"
else
    echo "Painel disponível em: http://${IP_LOCAL:-SEU_SERVIDOR}:$ADMIN_PORT"
fi
echo "Usuário: $ADMIN_USER"
if [[ "$POLLER_INSTALADO" -eq 1 ]]; then
    echo "Poller de eventos por conta: ativo (controllr-poller.timer)."
fi
echo ""
echo "IMPORTANTE:"
echo "  1. Configure a lista de IPs permitidos em Configurações assim"
echo "     que acessar (por padrão, sem essa lista, qualquer IP acessa"
echo "     a tela de login)."
if [[ "$DOMINIO_OK" -ne 1 ]]; then
    echo "  2. Sem domínio, o painel roda em HTTP simples. Se for acessível"
    echo "     pela internet, ative HTTPS: ./configurar-dominio.sh SEU_DOMINIO EMAIL"
fi
echo "=================================================="
