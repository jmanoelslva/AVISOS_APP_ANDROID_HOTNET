from pathlib import Path

import firebase_admin
from firebase_admin import credentials, messaging

_SERVICE_ACCOUNT_PATH = Path(__file__).resolve().parent / "service-account.json"
_TOPICO = "avisos_gerais"

_app = None


def _inicializar():
    global _app
    if _app is None:
        if not _SERVICE_ACCOUNT_PATH.exists():
            raise FileNotFoundError(
                "service-account.json não encontrado. Gere em: Firebase Console > "
                "Configurações do projeto > Contas de serviço > Gerar nova chave privada, "
                "e salve como server/aviso-broadcaster/service-account.json."
            )
        cred = credentials.Certificate(str(_SERVICE_ACCOUNT_PATH))
        _app = firebase_admin.initialize_app(cred)
    return _app


def enviar_aviso(titulo: str, corpo: str) -> str:
    """Envia o aviso (data-only) pro tópico avisos_gerais. Retorna o message id do FCM."""
    _inicializar()
    mensagem = messaging.Message(
        data={"title": titulo, "body": corpo},
        topic=_TOPICO,
        android=messaging.AndroidConfig(priority="high"),
    )
    return messaging.send(mensagem)


def enviar_para_conta(topico_conta: str, tipo: str, dados: dict) -> str:
    """Envia um evento (ex: pagamento confirmado) só pro tópico de uma conta
    específica (ver topico_conta_cpf em poller.py) — não pro avisos_gerais.
    `dados` vira campos extras no payload data-only, junto com "type".
    """
    _inicializar()
    payload = {"type": tipo, **{k: str(v) for k, v in dados.items()}}
    mensagem = messaging.Message(
        data=payload,
        topic=topico_conta,
        android=messaging.AndroidConfig(priority="high"),
    )
    return messaging.send(mensagem)
