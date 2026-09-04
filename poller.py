"""Ponto de entrada do poller (pagamento confirmado + chamado atualizado) —
roda uma vez e sai (chamado por systemd timer, ver controllr-poller.timer).
Sem loop/scheduler interno de propósito: mantém o processo simples e sem
estado entre execuções além do que já está em poller_state.json.

Reforço de fatura em atraso fica de fora por enquanto, se os dois casos
acima validarem bem em produção.
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
    ver topicoContaCpf() em SessionManager.kt. Precisa ficar idêntico dos
    dois lados, senão o push nunca chega a ninguém.
    """
    digitos = _SO_DIGITOS.sub("", cpf or "")
    return "conta_" + hashlib.sha256(digitos.encode("utf-8")).hexdigest()[:16]


def processar_faturas(cliente: ControllrClient, estado: dict, primeira_vez_faturas: bool) -> tuple[int, int]:
    faturas_vistas = estado.setdefault("faturas", {})
    faturas = cliente.buscar_faturas()

    notificadas = 0
    for fatura in faturas:
        pk = str(fatura.get("invoice_pk"))
        credito_atual = fatura.get("invoice_date_credit")
        credito_anterior = faturas_vistas.get(pk)

        # Só notifica na transição vazio -> preenchido, nunca de novo pra
        # quem já foi visto pago (evita reenviar todo ciclo), e nunca na
        # primeira execução (CRÍTICO: sem estado prévio, toda fatura já paga
        # dentro da janela pareceria "nova" e notificaria milhares de uma vez).
        if credito_atual and not credito_anterior and not primeira_vez_faturas:
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
                    access_log.registrar("poller_falha", detalhes=f"envio fatura {pk}: {e}")

        faturas_vistas[pk] = credito_atual

    return len(faturas), notificadas


def processar_chamados(cliente: ControllrClient, estado: dict, primeira_vez_chamados: bool) -> tuple[int, int]:
    chamados_vistos = estado.setdefault("chamados", {})
    chamados = cliente.buscar_chamados()

    notificadas = 0
    for chamado in chamados:
        pk = chamado.get("ticket_pk")
        pk_str = str(pk)
        ultimo_atual = chamado.get("ticket_date_last")
        ultimo_anterior = chamados_vistos.get(pk_str)

        if ultimo_atual and ultimo_atual != ultimo_anterior and not primeira_vez_chamados:
            cpf = chamado.get("client_doc1") or ""
            if cpf:
                try:
                    # Só notifica se quem mexeu por último foi a equipe, não
                    # o próprio cliente respondendo pelo app (op_client=True
                    # geraria uma notificação "seu chamado foi atualizado"
                    # sobre a mensagem que ele mesmo acabou de mandar).
                    if cliente.ultimo_op_e_de_staff(pk):
                        enviar_para_conta(
                            topico_conta_cpf(cpf),
                            "chamado_atualizado",
                            {
                                "ticket_pk": pk_str,
                                "ticket_protocol": chamado.get("ticket_protocol") or "",
                                "category_name": chamado.get("category_name") or "",
                            },
                        )
                        notificadas += 1
                except Exception as e:
                    access_log.registrar("poller_falha", detalhes=f"envio chamado {pk_str}: {e}")

        chamados_vistos[pk_str] = ultimo_atual

    return len(chamados), notificadas


def main() -> int:
    try:
        cfg = controllr_config.carregar()
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1

    estado = state_store.carregar()
    # Por categoria, não pelo arquivo inteiro — "faturas" pode já ter
    # baseline de um piloto anterior enquanto "chamados" ainda não tem
    # nenhuma (é exatamente esse caso hoje). Cada categoria nova adicionada
    # aqui precisa da própria checagem, senão repete o mesmo bug: tudo que
    # já está "ativo" na janela pareceria novo e notificaria em massa.
    primeira_vez_faturas = "faturas" not in estado
    primeira_vez_chamados = "chamados" not in estado

    cliente = ControllrClient(cfg["base_url"], cfg["usuario"], cfg["senha"])
    try:
        cliente.login()
    except Exception as e:
        access_log.registrar("poller_falha", detalhes=f"login: {e}")
        print(f"Falha ao logar no Controllr: {e}", file=sys.stderr)
        return 1

    try:
        total_faturas, notif_faturas = processar_faturas(cliente, estado, primeira_vez_faturas)
    except Exception as e:
        access_log.registrar("poller_falha", detalhes=f"busca de faturas: {e}")
        print(f"Falha ao consultar faturas: {e}", file=sys.stderr)
        return 1

    try:
        total_chamados, notif_chamados = processar_chamados(cliente, estado, primeira_vez_chamados)
    except Exception as e:
        access_log.registrar("poller_falha", detalhes=f"busca de chamados: {e}")
        print(f"Falha ao consultar chamados: {e}", file=sys.stderr)
        return 1

    state_store.salvar(estado)
    partes = []
    partes.append(
        f"{total_faturas} faturas, baseline gravada" if primeira_vez_faturas
        else f"{total_faturas} faturas ({notif_faturas} notificadas)"
    )
    partes.append(
        f"{total_chamados} chamados, baseline gravada" if primeira_vez_chamados
        else f"{total_chamados} chamados ({notif_chamados} notificados)"
    )
    access_log.registrar("poller_ciclo", detalhes=", ".join(partes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
