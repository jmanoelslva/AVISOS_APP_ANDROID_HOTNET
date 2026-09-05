"""Ponto de entrada do poller (pagamento confirmado + reforço de atraso +
chamado atualizado) — roda uma vez e sai (chamado por systemd timer, ver
controllr-poller.timer). Sem loop/scheduler interno de propósito: mantém
o processo simples e sem estado entre execuções além do que já está em
poller_state.json.
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


def _fatura_vale_notificar(fatura: dict) -> bool:
    """Filtra só `invoice_deleted` (exclusão lógica clara do registro).

    `invoice_valid=False` NÃO significa cliente inativo/cancelado, como se
    supôs numa rodada anterior — confirmado pelo usuário: significa que o
    pagamento foi feito manualmente no escritório, fora da plataforma
    bancária (o valor/data reais continuam em `invoice_amount_paid`/
    `invoice_date_credit`, normalmente). Chegou a filtrar erroneamente um
    pagamento real feito assim, sem notificar o cliente — por isso não é
    mais usado como filtro aqui.
    """
    return not fatura.get("invoice_deleted")


def processar_pagamentos(faturas: list[dict], estado: dict, primeira_vez: bool) -> int:
    faturas_vistas = estado.setdefault("faturas", {})
    notificadas = 0
    for fatura in faturas:
        pk = str(fatura.get("invoice_pk"))
        credito_atual = fatura.get("invoice_date_credit")
        credito_anterior = faturas_vistas.get(pk)

        # Só notifica na transição vazio -> preenchido, nunca de novo pra
        # quem já foi visto pago (evita reenviar todo ciclo), e nunca na
        # primeira execução (CRÍTICO: sem estado prévio, toda fatura já paga
        # dentro da janela pareceria "nova" e notificaria milhares de uma vez).
        if credito_atual and not credito_anterior and not primeira_vez and _fatura_vale_notificar(fatura):
            cpf = fatura.get("client_doc1") or ""
            if cpf:
                try:
                    enviar_para_conta(
                        topico_conta_cpf(cpf),
                        "pagamento_confirmado",
                        {
                            "invoice_pk": pk,
                            "contract_number": fatura.get("contract_number") or "",
                            # invoice_amount_paid, não invoice_amount_document: 23% das
                            # faturas pagas na amostra têm juros/multa somados ou
                            # desconto de pontualidade — o valor do documento original
                            # fica errado quase 1 em cada 4 vezes.
                            "invoice_amount_paid": fatura.get("invoice_amount_paid") or "",
                            "invoice_date_due": fatura.get("invoice_date_due") or "",
                        },
                    )
                    notificadas += 1
                except Exception as e:
                    access_log.registrar("poller_falha", detalhes=f"envio fatura {pk}: {e}")

        faturas_vistas[pk] = credito_atual

    return notificadas


def processar_atrasos(faturas: list[dict], estado: dict, primeira_vez: bool) -> int:
    """Reforço de atraso — um empurrão único quando a fatura vira atrasada
    (`invoice_late`), não um lembrete repetido enquanto ela continuar assim.
    Reaproveita a mesma lista de `buscar_faturas()` do pagamento confirmado
    (mesma janela de 90 dias já cobre faturas vencidas), sem chamada extra.
    """
    atrasadas_vistas = estado.setdefault("faturas_atrasadas", {})
    notificadas = 0
    for fatura in faturas:
        pk = str(fatura.get("invoice_pk"))
        ja_notificada = atrasadas_vistas.get(pk, False)

        if (
            fatura.get("invoice_late")
            and not fatura.get("invoice_date_credit")
            and not ja_notificada
            and not primeira_vez
            and _fatura_vale_notificar(fatura)
        ):
            cpf = fatura.get("client_doc1") or ""
            if cpf:
                try:
                    enviar_para_conta(
                        topico_conta_cpf(cpf),
                        "fatura_atrasada",
                        {
                            "invoice_pk": pk,
                            "contract_number": fatura.get("contract_number") or "",
                            "invoice_amount_document": fatura.get("invoice_amount_document") or "",
                            "invoice_date_due": fatura.get("invoice_date_due") or "",
                        },
                    )
                    notificadas += 1
                    atrasadas_vistas[pk] = True
                except Exception as e:
                    access_log.registrar("poller_falha", detalhes=f"envio atraso fatura {pk}: {e}")
        elif fatura.get("invoice_late"):
            # Já notificado antes (ou baseline) — só garante que fica marcado,
            # sem reenviar.
            atrasadas_vistas.setdefault(pk, True)

    return notificadas


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
    # Por categoria, não pelo arquivo inteiro — cada categoria nova adicionada
    # aqui precisa da própria checagem, senão repete o mesmo bug já corrigido
    # duas vezes: tudo que já está "ativo" na janela pareceria novo e
    # notificaria em massa na primeira vez que aquela categoria rodar.
    primeira_vez_pagamentos = "faturas" not in estado
    primeira_vez_atrasos = "faturas_atrasadas" not in estado
    primeira_vez_chamados = "chamados" not in estado

    cliente = ControllrClient(cfg["base_url"], cfg["usuario"], cfg["senha"])
    try:
        cliente.login()
    except Exception as e:
        access_log.registrar("poller_falha", detalhes=f"login: {e}")
        print(f"Falha ao logar no Controllr: {e}", file=sys.stderr)
        return 1

    try:
        faturas = cliente.buscar_faturas()
    except Exception as e:
        access_log.registrar("poller_falha", detalhes=f"busca de faturas: {e}")
        print(f"Falha ao consultar faturas: {e}", file=sys.stderr)
        return 1

    notif_pagamentos = processar_pagamentos(faturas, estado, primeira_vez_pagamentos)
    notif_atrasos = processar_atrasos(faturas, estado, primeira_vez_atrasos)

    try:
        total_chamados, notif_chamados = processar_chamados(cliente, estado, primeira_vez_chamados)
    except Exception as e:
        access_log.registrar("poller_falha", detalhes=f"busca de chamados: {e}")
        print(f"Falha ao consultar chamados: {e}", file=sys.stderr)
        return 1

    state_store.salvar(estado)
    partes = []
    partes.append(
        f"{len(faturas)} faturas, baseline pagamento gravada" if primeira_vez_pagamentos
        else f"{len(faturas)} faturas ({notif_pagamentos} pagamentos notificados)"
    )
    partes.append(
        "baseline atraso gravada" if primeira_vez_atrasos
        else f"{notif_atrasos} atrasos notificados"
    )
    partes.append(
        f"{total_chamados} chamados, baseline gravada" if primeira_vez_chamados
        else f"{total_chamados} chamados ({notif_chamados} notificados)"
    )
    access_log.registrar("poller_ciclo", detalhes=", ".join(partes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
