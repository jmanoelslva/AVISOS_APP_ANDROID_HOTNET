# Changelog

Todas as mudanças relevantes do painel de avisos e do poller de eventos por conta.
Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).

## [1.2.0] - 2026-10-16

### Adicionado
- Enviar aviso: prévia ao vivo de como a notificação aparece (recolhida, aberta e
  no sino do app), contadores de caracteres e alerta quando o texto passa do que
  cabe recolhido.
- Paleta de emojis por assunto (Rede, Horário, Status, Atendimento) no envio e nos
  modelos; insere onde está o cursor. A lista fica em `painel_info.py`.
- Confirmação de envio numa janela do próprio painel, com a notificação exata
  (antes era o `confirm()` do navegador).
- "Últimos avisos enviados" com "Usar de novo" (o log passa a guardar também a
  mensagem do aviso).
- Cartão "Notificações automáticas" com último ciclo do poller, próximo e falhas
  em 24h; avisa quando o poller parece parado.
- Modelos em cartões no envio; "Usar" na página Modelos abre o envio preenchido.
- Logs com filtros (Avisos, Acessos, Poller, Falhas), etiquetas, nomes legíveis
  dos eventos do poller e hora relativa; ciclos sem notificação ficam ocultos
  por padrão.

### Alterado
- Identidade alinhada ao app: laranja sólido #C94300 (botões com contraste
  melhor), nome "Avisos HOTNET", menu lateral no computador e menu da conta
  (Minha senha, Sair) no topo.
- Servidor recusa título acima de 80 e mensagem acima de 500 caracteres.
- `install.sh` copia também `access_log.py` e `painel_info.py`.

### Como atualizar o servidor
```bash
cd /opt/aviso-broadcaster && git pull
chown -R aviso-broadcaster: /opt/aviso-broadcaster
systemctl restart aviso-broadcaster
```
O poller não muda e não precisa reiniciar.

## [1.1.0] - 2026-10-16

### Adicionado
- Poller: a notificação de **pagamento confirmado** passa a levar a data em que o
  pagamento caiu (`invoice_date_credit`, a mesma que o app mostra em "Pago em" na
  tela Boletos). O app HOTNET 2.5.2 exibe: título "Pagamento de R$ 50,00 confirmado"
  e texto "Pago em 18/10/2026 · boleto com vencimento em 20/10 · Contrato 696".
  Versões do app sem esse suporte ignoram o campo novo.

### Como atualizar o servidor
Só o `poller.py` mudou. O serviço é `oneshot` disparado pelo timer, então basta
copiar o arquivo; o próximo ciclo já usa a versão nova (não precisa reiniciar nada):

```bash
cp poller.py /opt/aviso-broadcaster/
chown aviso-broadcaster: /opt/aviso-broadcaster/poller.py
```

## [1.0.0] - 2026-09-04

Estado em produção desde o piloto de push por conta.

### Adicionado
- Painel Flask de avisos gerais (tópico FCM `avisos_gerais`), com Gunicorn, CSRF,
  usuários, modelos, logs e tema claro/escuro.
- Poller de eventos por conta (tópico `conta_<hash do CPF>`): pagamento confirmado,
  chamado atualizado pela equipe, fatura em atraso (empurrão único) e boleto que
  vence amanhã (com "Copiar código Pix"; substituiu o `VencimentoWorker` do app).
- `install.sh` / `uninstall.sh` e serviços systemd (`aviso-broadcaster`,
  `controllr-poller.timer`).

### Corrigido
- Primeira execução do poller só grava a baseline (não notifica nada).
- `invoice_valid=false` não é mais tratado como cliente inativo (é pagamento manual
  no escritório).
- Pagamento confirmado usa `invoice_amount_paid` (valor realmente pago) em vez do
  valor do documento.

[1.2.0]: https://github.com/jmanoelslva/AVISOS_APP_ANDROID_HOTNET/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/jmanoelslva/AVISOS_APP_ANDROID_HOTNET/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/jmanoelslva/AVISOS_APP_ANDROID_HOTNET/releases/tag/v1.0.0
