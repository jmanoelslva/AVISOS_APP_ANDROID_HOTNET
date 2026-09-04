"""Ponto de entrada do poller de pagamento — roda uma vez e sai (chamado
por systemd timer, ver controllr-poller.timer). Sem loop/scheduler interno
de propósito: mantém o processo simples e sem estado entre execuções além
do que já está em poller_state.json.

Piloto: só confirmação de pagamento (invoice_date_credit passando de vazio
pra preenchido). Chamados e reforço de atraso ficam pra depois, se esse
piloto validar bem.
"""
import hashlib
import re
import sys

import access_log
import controllr_config
import state_store
from controllr_client import ControllrClient
from fcm_sender import enviar_para_conta

_SO_DIGITOS = re.compile(r"\D+")


def topico_conta_cpf(cpf: str) -> str:
    """Mesmo cálculo que o app Android faz ao assinar o tópico no login —
    ver topicoContaCpf() em SessionManager.kt/AuthRepository.kt. Precisa
    ficar idêntico dos dois lados, senão o push nunca chega a ninguém.
    """
    digitos = _SO_DIGITOS.sub("", cpf or "")
    return "conta_" + hashlib.sha256(digitos.encode("utf-8")).hexdigest()[:16]


def main() -> int:
    try:
        cfg = controllr_config.carregar()
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1

    estado = state_store.carregar()
    faturas_vistas = estado.setdefault("faturas", {})

    cliente = ControllrClient(cfg["base_url"], cfg["usuario"], cfg["senha"])
    try:
        cliente.login()
        faturas = cliente.buscar_faturas()
    except Exception as e:
        access_log.registrar("poller_falha", detalhes=f"busca de faturas: {e}")
        print(f"Falha ao consultar Controllr: {e}", file=sys.stderr)
        return 1

    notificadas = 0
    for fatura in faturas:
        pk = str(fatura.get("invoice_pk"))
        credito_atual = fatura.get("invoice_date_credit")
        credito_anterior = faturas_vistas.get(pk)

        # Só notifica na transição vazio -> preenchido, nunca de novo pra
        # quem já foi visto pago (evita reenviar todo ciclo).
        if credito_atual and not credito_anterior:
            cpf = fatura.get("client_doc1") or ""
            if cpf:
                try:
                    enviar_para_conta(
                        topico_conta_cpf(cpf),
                        "pagamento_confirmado",
                        {
                            "invoice_pk": pk,
                            "contract_number": fatura.get("contract_number") or "",
                            "invoice_amount_document": fatura.get("invoice_amount_document") or "",
                        },
                    )
                    notificadas += 1
                except Exception as e:
                    access_log.registrar(
                        "poller_falha", detalhes=f"envio fatura {pk}: {e}"
                    )

        faturas_vistas[pk] = credito_atual

    state_store.salvar(estado)
    access_log.registrar(
        "poller_ciclo",
        detalhes=f"{len(faturas)} faturas verificadas, {notificadas} notificações enviadas",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
