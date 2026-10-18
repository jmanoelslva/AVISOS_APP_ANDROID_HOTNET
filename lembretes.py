"""Configuração dos lembretes automáticos do poller, editada no painel (aba Automáticos)
e gravada em config.json na chave "lembretes":

- dias_antes: com quantos dias de antecedência avisar o vencimento (1 = véspera, até 7;
  0 = desativado). Um único lembrete por boleto.
- atraso_ativo: se o aviso de boleto em atraso sai (padrão sim).
- inicio/fim: horário em que lembretes de vencimento e de atraso podem sair. Fora
  dele o poller espera o próximo ciclo dentro do horário (nada se perde).
  Pagamento confirmado e chamado respondido continuam saindo na hora.
- pagamento_dias: só avisa pagamento com crédito de até N dias (1 a 30, padrão 5).
  Crédito mais antigo é fatura que o poller voltou a ver, não pagamento novo.
- janela_antes/janela_depois: faturas consultadas no Controllr, pelo vencimento,
  de N dias atrás (15 a 90, padrão 90) até N dias à frente (7 a 90, padrão 30).
"""
import datetime
import json
import re
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

DESATIVADO = 0
DIAS_PERMITIDOS = tuple(range(1, 8))
PADRAO = {
    "dias_antes": 1, "atraso_ativo": True, "inicio": "08:00", "fim": "20:00",
    "pagamento_dias": 5, "janela_antes": 90, "janela_depois": 30,
}
# (mínimo, máximo) de cada campo numérico. janela_depois começa em 7 para cobrir
# o maior dias_antes; janela_antes não passa de 90.
LIMITES = {"pagamento_dias": (1, 30), "janela_antes": (15, 90), "janela_depois": (7, 90)}

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
    cfg = {
        "dias_antes": dias,
        "atraso_ativo": atraso if isinstance(atraso, bool) else PADRAO["atraso_ativo"],
        "inicio": inicio,
        "fim": fim,
    }
    for campo, (minimo, maximo) in LIMITES.items():
        valor = bruto.get(campo)
        ok = isinstance(valor, int) and not isinstance(valor, bool) and minimo <= valor <= maximo
        cfg[campo] = valor if ok else PADRAO[campo]
    return cfg


_NOMES = {
    "pagamento_dias": "o prazo do pagamento confirmado",
    "janela_antes": "a busca para trás",
    "janela_depois": "a busca à frente",
}


def validar_formulario(
    dias_antes: str, inicio: str, fim: str, atraso: str = "1",
    pagamento_dias: str = "", janela_antes: str = "", janela_depois: str = "",
) -> tuple[dict | None, str]:
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
    cfg = {"dias_antes": dias, "atraso_ativo": atraso == "1", "inicio": inicio, "fim": fim}
    for campo, texto in (("pagamento_dias", pagamento_dias), ("janela_antes", janela_antes), ("janela_depois", janela_depois)):
        minimo, maximo = LIMITES[campo]
        try:
            valor = int(texto)
        except (TypeError, ValueError):
            return None, f"preencha {_NOMES[campo]}"
        if not minimo <= valor <= maximo:
            return None, f"{_NOMES[campo]} precisa ficar entre {minimo} e {maximo} dias"
        cfg[campo] = valor
    return cfg, ""


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
    return (
        f"{quando}{atraso} · das {cfg['inicio']} às {cfg['fim']}"
        f" · pagamento de até {cfg['pagamento_dias']} dias"
        f" · busca de {cfg['janela_antes']} dias atrás a {cfg['janela_depois']} à frente"
    )
