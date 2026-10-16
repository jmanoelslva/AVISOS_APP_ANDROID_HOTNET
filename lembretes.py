"""Configuração dos lembretes automáticos do poller, editada no painel (Configurações)
e gravada em config.json na chave "lembretes":

- dias_antes: com quantos dias de antecedência avisar o vencimento (1 = véspera, até 7;
  0 = desativado). Um único lembrete por boleto.
- atraso_ativo: se o aviso de boleto em atraso sai (padrão sim).
- inicio/fim: horário em que lembretes de vencimento e de atraso podem sair. Fora
  dele o poller espera o próximo ciclo dentro do horário (nada se perde).
  Pagamento confirmado e chamado respondido continuam saindo na hora.
"""
import datetime
import json
import re
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

DESATIVADO = 0
DIAS_PERMITIDOS = tuple(range(1, 8))
PADRAO = {"dias_antes": 1, "atraso_ativo": True, "inicio": "08:00", "fim": "20:00"}

_HORA = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def normalizar(bruto) -> dict:
    """Valores inválidos ou ausentes caem no padrão, campo a campo."""
    bruto = bruto if isinstance(bruto, dict) else {}
    dias = bruto.get("dias_antes")
    if not (isinstance(dias, int) and not isinstance(dias, bool) and (dias in DIAS_PERMITIDOS or dias == DESATIVADO)):
        dias = PADRAO["dias_antes"]
    inicio = bruto.get("inicio") if isinstance(bruto.get("inicio"), str) and _HORA.match(bruto["inicio"]) else None
    fim = bruto.get("fim") if isinstance(bruto.get("fim"), str) and _HORA.match(bruto["fim"]) else None
    if not (inicio and fim and inicio < fim):
        inicio, fim = PADRAO["inicio"], PADRAO["fim"]
    atraso = bruto.get("atraso_ativo")
    return {
        "dias_antes": dias,
        "atraso_ativo": atraso if isinstance(atraso, bool) else PADRAO["atraso_ativo"],
        "inicio": inicio,
        "fim": fim,
    }


def validar_formulario(dias_antes: str, inicio: str, fim: str, atraso: str = "1") -> tuple[dict | None, str]:
    """Do formulário do painel: devolve (config, "") ou (None, motivo)."""
    try:
        dias = int(dias_antes)
    except (TypeError, ValueError):
        return None, "escolha a antecedência"
    if dias not in DIAS_PERMITIDOS and dias != DESATIVADO:
        return None, "escolha entre 1 e 7 dias ou desativado"
    if not (_HORA.match(inicio or "") and _HORA.match(fim or "")):
        return None, "horário inválido (use HH:MM)"
    if inicio >= fim:
        return None, "o horário de início precisa ser antes do fim"
    if atraso not in ("0", "1"):
        return None, "escolha se o aviso de atraso fica ativado"
    return {"dias_antes": dias, "atraso_ativo": atraso == "1", "inicio": inicio, "fim": fim}, ""


def ler() -> dict:
    """Só leitura, para o poller (que roda como o mesmo usuário do painel). Não usa
    config_store.carregar() de propósito: aquele pode regravar o arquivo. Arquivo
    ausente, ilegível ou no meio de uma gravação do painel → padrão."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return normalizar(json.load(f).get("lembretes"))
    except (OSError, ValueError, AttributeError):
        return normalizar(None)


def dentro_do_horario(cfg: dict, agora: datetime.datetime | None = None) -> bool:
    hhmm = (agora or datetime.datetime.now()).strftime("%H:%M")
    return cfg["inicio"] <= hhmm < cfg["fim"]


def descrever(cfg: dict) -> str:
    """Ex.: "3 dias antes do vencimento · das 08:00 às 20:00"."""
    d = cfg["dias_antes"]
    if d == DESATIVADO:
        quando = "Lembrete de vencimento desativado"
    else:
        quando = "Na véspera do vencimento" if d == 1 else f"{d} dias antes do vencimento"
    atraso = "" if cfg.get("atraso_ativo", True) else " · aviso de atraso desativado"
    return f"{quando}{atraso} · das {cfg['inicio']} às {cfg['fim']}"
