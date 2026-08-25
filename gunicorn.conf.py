"""Configuração do Gunicorn — lê a porta do mesmo config.json usado pelo
painel, pra manter o fluxo de "trocar a porta em Configurações e reiniciar
o serviço" funcionando igual ao antes.
"""
import config_store

_cfg = config_store.carregar()

bind = f"0.0.0.0:{_cfg.get('port', config_store.DEFAULT_PORT)}"

# Só 1 worker de propósito: o bloqueio por tentativas de login errado
# (_tentativas_login, em app.py) é guardado em memória do processo — com
# mais de um worker, cada processo teria sua própria contagem e o
# bloqueio de 5 tentativas viraria "5 tentativas por worker". Painel de
# baixo tráfego, uso único (um admin), não precisa de concorrência real.
workers = 1
worker_class = "sync"

accesslog = "-"
errorlog = "-"
