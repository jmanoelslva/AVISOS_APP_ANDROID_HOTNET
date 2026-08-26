"""Configuração do Gunicorn — lê a porta do mesmo config.json usado pelo
painel, pra manter o fluxo de "trocar a porta em Configurações e reiniciar
o serviço" funcionando igual ao antes.
"""
import config_store

_cfg = config_store.carregar()

# "[::]" (IPv6 wildcard) já aceita conexões IPv4 também, no Linux com o
# padrão net.ipv6.bindv6only=0 (caso do Debian) — é uma única escuta
# dual-stack. Tentar escutar em "0.0.0.0" E "[::]" ao mesmo tempo dá erro
# de "endereço já em uso", por isso é só esse.
bind = f"[::]:{_cfg.get('port', config_store.DEFAULT_PORT)}"

# Só 1 worker de propósito: o bloqueio por tentativas de login errado
# (_tentativas_login, em app.py) é guardado em memória do processo — com
# mais de um worker, cada processo teria sua própria contagem e o
# bloqueio de 5 tentativas viraria "5 tentativas por worker". Painel de
# baixo tráfego, uso único (um admin), não precisa de concorrência real.
workers = 1
worker_class = "sync"

accesslog = "-"
errorlog = "-"
