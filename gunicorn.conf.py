"""Configuração do Gunicorn — lê a porta (e o domínio, se houver) do mesmo
config.json do painel. Trocar a porta em Ajustes manda SIGHUP ao master, que
reexecuta este arquivo e passa a escutar na porta nova.
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

# Só 1 processo de propósito: o bloqueio por tentativas de login errado
# (_tentativas_login, em app.py) é guardado em memória — com mais de um
# processo, cada um teria sua própria contagem e o bloqueio de 5 tentativas
# viraria "5 tentativas por processo". Threads dividem a mesma memória.
workers = 1
# gthread, não sync: o sync atende uma conexão por vez e fica preso numa
# conexão aberta sem pedido (o Chrome abre essas "de reserva"), travando o
# painel para todos até 30 s. O gthread só ocupa uma thread quando chega
# dado na conexão. Gravações em arquivo têm trava (access_log, config_store).
worker_class = "gthread"
threads = 4

accesslog = "-"
errorlog = "-"
