#!/usr/bin/env bash
# Coloca o painel atrás de um domínio com HTTPS (Let's Encrypt), com renovação
# automática do certificado. Também desfaz (volta ao acesso por IP e porta).
#
# Uso (como root, na pasta do painel):
#   ./configurar-dominio.sh painel.exemplo.com.br [email@exemplo.com.br]
#   ./configurar-dominio.sh --remover
#
# Requisitos: o domínio já apontando (registro A e/ou AAAA) para este servidor
# e as portas 80 e 443 liberadas no firewall. O Let's Encrypt valida pela 80.
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/aviso-broadcaster}"
SERVICE="aviso-broadcaster"
DROPIN_DIR="/etc/systemd/system/${SERVICE}.service.d"
DROPIN="${DROPIN_DIR}/dominio.conf"
SITE="aviso-broadcaster"

erro() { echo "ERRO: $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || erro "execute como root."
[[ -x "$INSTALL_DIR/venv/bin/python" ]] || erro "painel não encontrado em $INSTALL_DIR (rode o install.sh antes)."

# Grava ou apaga a chave "dominio" no config.json, pelo próprio config_store.
gravar_dominio() {
    (cd "$INSTALL_DIR" && "$INSTALL_DIR/venv/bin/python" - "$1" <<'PYEOF'
import sys
import config_store

cfg = config_store.carregar()
if sys.argv[1]:
    cfg["dominio"] = sys.argv[1]
else:
    cfg.pop("dominio", None)
config_store.salvar(cfg)
PYEOF
    )
    chown "$SERVICE:$SERVICE" "$INSTALL_DIR/config.json"
}

porta_do_painel() {
    "$INSTALL_DIR/venv/bin/python" -c "import json; print(json.load(open('$INSTALL_DIR/config.json')).get('port', 8765))"
}

servidor_web() {
    # Usa o Apache se ele já estiver rodando (não dá para ter os dois na porta 80).
    if systemctl is-active --quiet apache2; then echo apache; else echo nginx; fi
}

if [[ "${1:-}" == "--remover" ]]; then
    echo "== Voltando ao acesso por IP e porta =="
    rm -f "/etc/nginx/sites-enabled/$SITE" "/etc/nginx/sites-available/$SITE"
    if command -v a2dissite >/dev/null; then
        a2dissite -q "$SITE" "$SITE-le-ssl" 2>/dev/null || true
        rm -f "/etc/apache2/sites-available/$SITE.conf" "/etc/apache2/sites-available/$SITE-le-ssl.conf"
    fi
    systemctl reload nginx 2>/dev/null || true
    systemctl reload apache2 2>/dev/null || true
    rm -f "$DROPIN"
    gravar_dominio ""
    systemctl daemon-reload
    systemctl restart "$SERVICE"
    echo "Pronto. Painel em http://$(hostname -I | awk '{print $1}'):$(porta_do_painel)"
    echo "O certificado continua em /etc/letsencrypt; para apagar: certbot delete"
    exit 0
fi

DOMINIO="${1:-}"
EMAIL="${2:-}"
[[ -n "$DOMINIO" ]] || erro "informe o domínio. Ex.: ./configurar-dominio.sh painel.exemplo.com.br email@exemplo.com.br"
[[ "$DOMINIO" =~ ^([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$ ]] || erro "domínio inválido: $DOMINIO"
if [[ -n "$EMAIL" && ! "$EMAIL" =~ ^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$ ]]; then
    erro "e-mail inválido: $EMAIL"
fi

PORTA="$(porta_do_painel)"
WEB="$(servidor_web)"

echo "== Conferindo o DNS de $DOMINIO =="
IPS_DOMINIO="$(getent ahosts "$DOMINIO" | awk '{print $1}' | sort -u || true)"
[[ -n "$IPS_DOMINIO" ]] || erro "$DOMINIO não resolve. Crie o registro A/AAAA apontando para este servidor e tente de novo."
IPS_LOCAIS=" $(hostname -I) "
APONTA=0
for ip in $IPS_DOMINIO; do
    [[ "$IPS_LOCAIS" == *" $ip "* ]] && APONTA=1
done
if [[ $APONTA -eq 0 ]]; then
    echo "AVISO: $DOMINIO resolve para: $(echo $IPS_DOMINIO)"
    echo "       e nenhum desses IPs é deste servidor ($(hostname -I))."
    echo "       Se houver NAT/proxy na frente, pode estar certo; senão, o certificado vai falhar."
    read -rp "Continuar mesmo assim? [s/N]: " CONT
    [[ "$CONT" =~ ^[Ss]$ ]] || exit 1
fi

if [[ "$WEB" == nginx ]] && ss -ltnH 'sport = :80' | grep -q . && ! systemctl is-active --quiet nginx; then
    erro "a porta 80 já está em uso por outro programa (veja: ss -ltnp 'sport = :80'). Libere-a ou use o Apache/Nginx que já estiver nela."
fi

echo "== Instalando $WEB e certbot =="
apt-get update -qq
if [[ "$WEB" == nginx ]]; then
    apt-get install -y -qq nginx certbot python3-certbot-nginx
else
    apt-get install -y -qq certbot python3-certbot-apache
    a2enmod -q proxy proxy_http headers ssl rewrite >/dev/null
fi

# Se algo falhar daqui até o certificado sair, tira o site: o painel nunca fica
# exposto pelo domínio só em HTTP.
desfazer_site() {
    echo "Falhou. Removendo o site de $DOMINIO; o painel continua por IP e porta." >&2
    rm -f "/etc/nginx/sites-enabled/$SITE" "/etc/nginx/sites-available/$SITE"
    if [[ "$WEB" == apache ]]; then a2dissite -q "$SITE" 2>/dev/null || true; fi
    systemctl reload "$([[ "$WEB" == nginx ]] && echo nginx || echo apache2)" 2>/dev/null || true
}
trap desfazer_site ERR

echo "== Configurando $DOMINIO → painel (127.0.0.1:$PORTA) =="
if [[ "$WEB" == nginx ]]; then
    cat > "/etc/nginx/sites-available/$SITE" <<EOF
# Painel Avisos HOTNET (gerado por configurar-dominio.sh). O certbot acrescenta o HTTPS.
server {
    listen 80;
    listen [::]:80;
    server_name $DOMINIO;

    client_max_body_size 1m;

    location / {
        proxy_pass http://127.0.0.1:$PORTA;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$remote_addr;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 60s;
    }
}
EOF
    ln -sf "/etc/nginx/sites-available/$SITE" "/etc/nginx/sites-enabled/$SITE"
    nginx -t
    systemctl enable --now nginx
    systemctl reload nginx
else
    cat > "/etc/apache2/sites-available/$SITE.conf" <<EOF
# Painel Avisos HOTNET (gerado por configurar-dominio.sh). O certbot acrescenta o HTTPS.
<VirtualHost *:80>
    ServerName $DOMINIO
    ProxyPreserveHost On
    ProxyPass / http://127.0.0.1:$PORTA/
    ProxyPassReverse / http://127.0.0.1:$PORTA/
    # Um único IP, o da conexão: o que o navegador mandar nesse cabeçalho é descartado.
    RequestHeader set X-Forwarded-For "%{REMOTE_ADDR}s"
    RequestHeader set X-Forwarded-Proto "expr=%{REQUEST_SCHEME}"
</VirtualHost>
EOF
    a2ensite -q "$SITE"
    apache2ctl configtest
    systemctl reload apache2
fi

if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
    echo "== Liberando 80 e 443 no ufw =="
    ufw allow 80/tcp >/dev/null
    ufw allow 443/tcp >/dev/null
fi

echo "== Emitindo o certificado Let's Encrypt =="
CONTA=(--register-unsafely-without-email)
[[ -n "$EMAIL" ]] && CONTA=(-m "$EMAIL")
certbot "--$WEB" -d "$DOMINIO" --non-interactive --agree-tos "${CONTA[@]}" --redirect
trap - ERR

echo "== Renovação automática =="
systemctl enable --now certbot.timer
certbot renew --dry-run --cert-name "$DOMINIO"

echo "== Painel só para o proxy local (HTTPS obrigatório) =="
mkdir -p "$DROPIN_DIR"
cat > "$DROPIN" <<EOF
# Gerado por configurar-dominio.sh. Remova com: ./configurar-dominio.sh --remover
[Service]
# Cookie de sessão só por HTTPS.
Environment="AVISO_BROADCASTER_HTTPS=1"
# Confia no IP real que o $WEB local manda (lista de IPs permitidos).
Environment="AVISO_BROADCASTER_PROXY=1"
EOF
gravar_dominio "$DOMINIO"
systemctl daemon-reload
systemctl restart "$SERVICE"

echo ""
echo "=================================================="
echo "Painel disponível em: https://$DOMINIO"
echo "Certificado: Let's Encrypt, renovação automática (certbot.timer, 2x ao dia;"
echo "renova quando faltam 30 dias). Confira: systemctl list-timers certbot.timer"
echo "A porta $PORTA agora só atende o $WEB local; o acesso por IP:porta foi fechado."
[[ -z "$EMAIL" ]] && echo "Sem e-mail: você não recebe aviso do Let's Encrypt se a renovação falhar."
echo "Para voltar ao acesso por IP: ./configurar-dominio.sh --remover"
echo "=================================================="
