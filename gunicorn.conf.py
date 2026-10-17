"""Configuração do Gunicorn — lê a porta do mesmo config.json usado pelo
painel, pra manter o fluxo de "trocar a porta em Configurações e reiniciar
o serviço" funcionando igual ao antes.
"""
import json

import config_store

# Lido direto do disco (não pelo cache de config_store): ao trocar a porta no
# painel, o app manda SIGHUP pro master, que reexecuta este arquivo e passa a
# escutar na porta nova. Com o cache, o master continuaria vendo a porta antiga.
try:
    with open(config_store.CONFIG_PATH, "r", encoding="utf-8") as _f:
        _cfg = json.load(_f)
except (OSError, ValueError):
    _cfg = config_store.carregar()

# "[::]" (IPv6 wildcard) já aceita conexões IPv4 também, no Linux com o
# padrão net.ipv6.bindv6only=0 (caso do Debian) — é uma única escuta
# dual-stack. Tentar escutar em "0.0.0.0" E "[::]" ao mesmo tempo dá erro
# de "endereço já em uso", por isso é só esse.
_porta = _cfg.get("port", config_store.DEFAULT_PORT)
# Com domínio (configurar-dominio.sh), só o Nginx/Apache local fala com o painel:
# escuta apenas em 127.0.0.1, e o acesso de fora é só por HTTPS.
bind = f"127.0.0.1:{_porta}" if _cfg.get("dominio") else f"[::]:{_porta}"

# Só 1 worker de propósito: o bloqueio por tentativas de login errado
# (_tentativas_login, em app.py) é guardado em memória do processo — com
# mais de um worker, cada processo teria sua própria contagem e o
# bloqueio de 5 tentativas viraria "5 tentativas por worker". Painel de
# baixo tráfego, uso único (um admin), não precisa de concorrência real.
workers = 1
worker_class = "sync"

accesslog = "-"
errorlog = "-"
