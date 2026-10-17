import re

SENHA_MAX = 128  # werkzeug faz o hash de qualquer tamanho; o limite evita pedido gigante de propósito


def validar_forca_senha(senha: str) -> list[str]:
    """Retorna a lista de requisitos que a senha NÃO atende (vazia = ok)."""
    problemas = []
    if len(senha) < 8:
        problemas.append("mínimo de 8 caracteres")
    if len(senha) > SENHA_MAX:
        problemas.append(f"máximo de {SENHA_MAX} caracteres")
    if not re.search(r"[A-Z]", senha):
        problemas.append("pelo menos 1 letra maiúscula")
    if not re.search(r"[a-z]", senha):
        problemas.append("pelo menos 1 letra minúscula")
    if not re.search(r"[0-9]", senha):
        problemas.append("pelo menos 1 número")
    if not re.search(r"[^A-Za-z0-9]", senha):
        problemas.append("pelo menos 1 caractere especial")
    return problemas
