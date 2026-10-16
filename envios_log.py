"""Uma linha por notificação automática do poller (pagamento, atraso, lembrete,
chamado), com cliente e CPF/CNPJ, para a visão Notificações do Histórico.

Fica em envios.log, separado do acessos.log: um lote grande (ex.: a conciliação
da meia-noite) não empurra logins e avisos para fora do histórico. Guarda só os
últimos DIAS_RETENCAO dias. Só o poller escreve; o painel só lê.
"""
import json
import os
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parent / "envios.log"
DIAS_RETENCAO = 30
_FORMATO = "%Y-%m-%d %H:%M:%S"


def _recente(entrada: dict, corte: datetime) -> bool:
    try:
        return datetime.strptime(entrada.get("quando", ""), _FORMATO) >= corte
    except ValueError:
        return False


def _ler_todas() -> list[dict]:
    if not LOG_PATH.exists():
        return []
    entradas = []
    with open(LOG_PATH, "r", encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha:
                continue
            try:
                entradas.append(json.loads(linha))
            except json.JSONDecodeError:
                continue
    return entradas


def registrar_lote(envios: list[dict]) -> None:
    """Acrescenta os envios do ciclo (todos com o mesmo "quando") e descarta o
    que passou de DIAS_RETENCAO. Grava num temporário e troca de uma vez, para o
    painel nunca ler o arquivo pela metade."""
    if not envios and not LOG_PATH.exists():
        return
    quando = time.strftime(_FORMATO)
    corte = datetime.now() - timedelta(days=DIAS_RETENCAO)
    entradas = [e for e in _ler_todas() if _recente(e, corte)]
    entradas.extend({"quando": quando, **e} for e in envios)
    fd, temporario = tempfile.mkstemp(prefix=".envios-", dir=LOG_PATH.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for e in entradas:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        os.chmod(temporario, 0o600)
        os.replace(temporario, LOG_PATH)
    except BaseException:
        try:
            os.unlink(temporario)
        except OSError:
            pass
        raise


def listar() -> list[dict]:
    """Envios dos últimos DIAS_RETENCAO dias, mais recentes primeiro."""
    corte = datetime.now() - timedelta(days=DIAS_RETENCAO)
    return list(reversed([e for e in _ler_todas() if _recente(e, corte)]))
