# Changelog

Todas as mudanças relevantes do painel de avisos e do poller de eventos por conta.
Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).

## [1.4.0] - 2026-10-16

### Adicionado
- Histórico → **Notificações**: cada aviso automático do poller com o cliente
  (nome, CPF/CNPJ completo) e o que foi avisado: pagamento confirmado (valor,
  data do pagamento, vencimento, contrato), cobrança de atraso (vencimento,
  valor, data de bloqueio), lembrete antecipado (quantos dias faltam, valor)
  e chamado respondido (número e assunto). Envio que falhou aparece com o motivo.
- Cartões coloridos por tipo (verde, vermelho, âmbar, azul) com a contagem do
  período escolhido (hoje, 7 ou 30 dias) e o total de clientes avisados; clicar
  num cartão filtra a lista. Busca por nome, CPF com ou sem pontos, contrato ou
  número do chamado.
- `envios_log.py`: o poller grava uma linha por envio em `envios.log`
  (permissão 600, fora do git), guardado por 30 dias. Separado do `acessos.log`
  para um lote grande não empurrar logins e avisos para fora do histórico.

### Alterado
- Histórico guarda os últimos 1000 eventos (antes 500).
- `install.sh` copia também `envios_log.py`.

### Como atualizar o servidor
```bash
cd /opt/aviso-broadcaster && git pull
chown -R aviso-broadcaster: /opt/aviso-broadcaster
systemctl restart aviso-broadcaster
```
O poller pega o código novo sozinho no próximo ciclo. A lista de Notificações
começa vazia e se preenche a partir dele.

## [1.3.0] - 2026-10-16

### Adicionado
- Aba **Automáticos**: funcionamento do poller (último ciclo, próximo, falhas),
  quantos avisos de cada tipo saíram hoje e os ajustes dos lembretes.
- Lembrete de vencimento configurável: véspera, 2 a 7 dias antes ou desativado
  (padrão véspera). A véspera continua com o tipo `boleto_vence_amanha`; 2 a 7
  dias usam o tipo novo `boleto_vence_em` (com `dias` e `invoice_date_due`), que
  só o app 2.5.3+ mostra; versões anteriores ignoram.
- Aviso de boleto em atraso pode ser desativado (desligado, marca como visto sem
  avisar; ao religar, só os novos atrasos avisam).
- Horário de envio dos lembretes e atrasos (padrão 08:00 às 20:00; antes o aviso
  de véspera podia sair de madrugada). Fora do horário, espera o primeiro ciclo
  dentro dele. Pagamento e chamado continuam na hora.
- Troca de porta aplicada pelo próprio painel ("Salvar e aplicar"): SIGHUP no
  Gunicorn, sem root; só 1024 a 65535 e só se a porta estiver livre.
- Selo "Automáticos ok · HH:MM" no topo (amarelo com falhas, vermelho parado).
- Enviar: rascunho salvo no navegador e Ctrl+Enter para revisar.

### Alterado
- Visual: topo grafite com o logotipo oficial, laranja só em ação e seleção.
- Enviar em três colunas da mesma altura (modelos, texto, celular); prévia numa
  tela de bloqueio com abas Recolhida, Aberta e No sino; emojis num botão.
- Modelos em cartões, com editor e prévia numa janela.
- "Logs" virou **Histórico** (filtros, busca e opção numa linha só) e
  "Configurações" virou **Ajustes** (usuários e acesso lado a lado; novo
  usuário numa janela). Os lembretes saíram de Ajustes e foram para Automáticos.
- `install.sh` copia também `lembretes.py` e a pasta `static/`.

### Como atualizar o servidor
```bash
cd /opt/aviso-broadcaster && git pull
chown -R aviso-broadcaster: /opt/aviso-broadcaster
systemctl restart aviso-broadcaster
```
O poller usa a configuração nova no próximo ciclo (não precisa reiniciar).

## [1.2.1] - 2026-10-16

### Corrigido
- Enviar aviso: ao escolher um modelo com texto longo, a prévia "recolhida" esticava
  a página para os lados (barra de rolagem horizontal) e desalinhava o formulário.
- Cartões de baixo (Últimos avisos / Notificações automáticas) alinhados às colunas
  de cima.

### Alterado
- Menu volta a ser só as abas no topo, em qualquer largura de tela (sai o menu
  lateral do computador).

### Como atualizar o servidor
```bash
cd /opt/aviso-broadcaster && git pull
chown -R aviso-broadcaster: /opt/aviso-broadcaster
systemctl restart aviso-broadcaster
```

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

[1.3.0]: https://github.com/jmanoelslva/AVISOS_APP_ANDROID_HOTNET/compare/v1.2.1...v1.3.0
[1.2.1]: https://github.com/jmanoelslva/AVISOS_APP_ANDROID_HOTNET/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/jmanoelslva/AVISOS_APP_ANDROID_HOTNET/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/jmanoelslva/AVISOS_APP_ANDROID_HOTNET/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/jmanoelslva/AVISOS_APP_ANDROID_HOTNET/releases/tag/v1.0.0
