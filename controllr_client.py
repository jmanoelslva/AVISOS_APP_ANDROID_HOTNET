import datetime
import json

import requests

# Mesmo formato de filtro que o app Android usa (ver ConsumoRepository.kt/
# SuporteRepository.kt): array de {"field","oper","value"}. oper inferido
# do uso existente no app — 4 = ">=", 3 = "<=", 5 = "=". Nunca confirmado
# contra documentação oficial do Controllr, só por padrão observado.
_OPER_GTE = 4
_OPER_LTE = 3


def _conferir_completa(itens: list[dict], chave: str, total, nome: str) -> list[dict]:
    """Tira repetidos e falha se vier menos que o `total` informado pelo Controllr.
    Lista incompleta não pode seguir: a poda do estado esqueceria o que faltou e,
    quando voltasse, pareceria novidade (aviso repetido de pagamento antigo)."""
    unicos = list({str(i.get(chave)): i for i in itens}.values())
    if isinstance(total, int) and len(unicos) < total:
        raise RuntimeError(f"Busca de {nome} incompleta: {len(unicos)} de {total}")
    return unicos


class ControllrClient:
    """Sessão HTTP como o usuário admin dedicado (só leitura), pro poller
    consultar faturas de TODOS os clientes — algo bloqueado pra sessão de
    cliente comum (ver comentários em ClientApiService.kt no app Android).
    """

    def __init__(self, base_url: str, usuario: str, senha: str):
        self._base_url = base_url.rstrip("/") + "/"
        self._usuario = usuario
        self._senha = senha
        self._sessao = requests.Session()
        self._sessao.headers["User-Agent"] = "hotnet-controllr-poller/1.0"

    def login(self, timeout: float = 15.0) -> None:
        resp = self._sessao.post(
            self._base_url + "login",
            data={"username": self._usuario, "password": self._senha},
            timeout=timeout,
        )
        resp.raise_for_status()
        corpo = resp.json()
        if not corpo.get("success"):
            raise RuntimeError(f"Login no Controllr falhou: {corpo}")

    def buscar_faturas(self, dias_antes: int = 90, dias_depois: int = 30, timeout: float = 30.0) -> list[dict]:
        """Faturas com vencimento nos últimos `dias_antes` dias até `dias_depois`
        dias à frente (ajustáveis no painel) — evita puxar o histórico inteiro a cada ciclo. Pagina em
        blocos de 200 até a resposta vir vazia.

        Ordena por `invoice_pk` (único). Por `invoice_date_due` havia milhares de
        empates no mesmo dia e o Controllr devolvia cada página numa ordem
        diferente: ~1450 faturas repetidas e outras tantas faltando por consulta.
        Com a poda do estado, a fatura que sumia e voltava parecia paga agora e
        o cliente recebia "pagamento confirmado" de mês anterior.
        """
        hoje = datetime.date.today()
        inicio = (hoje - datetime.timedelta(days=dias_antes)).isoformat()
        fim = (hoje + datetime.timedelta(days=dias_depois)).isoformat()
        where = json.dumps([
            {"field": "invoice_date_due", "oper": _OPER_GTE, "value": inicio},
            {"field": "AND"},
            {"field": "invoice_date_due", "oper": _OPER_LTE, "value": fim},
        ])

        faturas: list[dict] = []
        start = 0
        limite = 200
        while True:
            resp = self._sessao.post(
                self._base_url + "invoice_ctl/invoice/list",
                data={
                    "action": "list",
                    "where": where,
                    "sort": "invoice_pk",
                    "dir": "ASC",
                    "start": start,
                    "limit": limite,
                },
                timeout=timeout,
            )
            resp.raise_for_status()
            corpo = resp.json()
            if not corpo.get("success"):
                raise RuntimeError(f"Busca de faturas falhou: {corpo}")
            pagina = corpo.get("results") or []
            faturas.extend(pagina)
            if len(pagina) < limite:
                break
            start += limite
        return _conferir_completa(faturas, "invoice_pk", corpo.get("total"), "faturas")

    def buscar_chamados(self, dias_janela: int = 7, timeout: float = 30.0) -> list[dict]:
        """Chamados com atividade (ticket_date_last) nos últimos `dias_janela`
        dias — evita puxar o histórico inteiro (~1800 chamados) a cada ciclo;
        um chamado só entra na janela de novo se algo mexer nele. Pagina em
        blocos de 200.
        """
        corte = (datetime.date.today() - datetime.timedelta(days=dias_janela)).isoformat()
        where = json.dumps([{"field": "ticket_date_last", "oper": _OPER_GTE, "value": corte}])

        chamados: list[dict] = []
        start = 0
        limite = 200
        while True:
            resp = self._sessao.post(
                self._base_url + "support_ctl/ticket/list",
                data={
                    "action": "list",
                    "where": where,
                    "sort": "ticket_pk",
                    "dir": "ASC",
                    "start": start,
                    "limit": limite,
                },
                timeout=timeout,
            )
            resp.raise_for_status()
            corpo = resp.json()
            if not corpo.get("success"):
                raise RuntimeError(f"Busca de chamados falhou: {corpo}")
            pagina = corpo.get("results") or []
            chamados.extend(pagina)
            if len(pagina) < limite:
                break
            start += limite
        return _conferir_completa(chamados, "ticket_pk", corpo.get("total"), "chamados")

    def ultimo_op_e_de_staff(self, ticket_pk: int, timeout: float = 15.0) -> bool:
        """True só se a operação mais recente do chamado foi escrita pela
        equipe (op_client=False) — evita notificar o cliente sobre a própria
        mensagem que ele acabou de mandar pelo app.
        """
        where = json.dumps([{"field": "ticket_pk", "oper": 5, "value": ticket_pk}])
        resp = self._sessao.post(
            self._base_url + "support_ctl/op/list",
            data={"where": where},
            timeout=timeout,
        )
        resp.raise_for_status()
        corpo = resp.json()
        if not corpo.get("success"):
            raise RuntimeError(f"Busca de operações do chamado {ticket_pk} falhou: {corpo}")
        operacoes = corpo.get("results") or []
        if not operacoes:
            return False
        ultima = max(operacoes, key=lambda op: op.get("op_pk") or 0)
        return ultima.get("op_client") is False
