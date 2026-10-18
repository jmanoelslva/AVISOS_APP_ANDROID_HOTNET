# Changelog

Mudanças do painel de avisos e do poller de eventos por conta.
Formato: [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/). Versões: [SemVer](https://semver.org/lang/pt-BR/).

Atualização do servidor (todas as versões, salvo indicação):
```bash
cd /opt/aviso-broadcaster && git pull
chown -R aviso-broadcaster: /opt/aviso-broadcaster
systemctl restart aviso-broadcaster
```
O poller roda por timer e usa o código novo no ciclo seguinte, sem reinício.

## [1.6.3] - 2026-10-18
Partes: poller.

### Corrigido
- Clientes recebiam "pagamento confirmado" de fatura antiga (ex.: mês 08). A busca de faturas ordenava por vencimento; com milhares de empates no mesmo dia, o Controllr repetia cerca de 1450 faturas e omitia outras tantas por consulta. A poda da 1.6.2 esquecia as omitidas e, quando voltavam, pareciam pagas agora. A busca ordena por `invoice_pk`, tira repetidos e falha se vier incompleta.
- Busca de chamados também ordena por `ticket_pk` e confere o total.
- Pagamento só é notificado com crédito de até 5 dias (`PAGAMENTO_DIAS_MAX`); fatura antiga que reaparece só é registrada.

## [1.6.2] - 2026-10-16
Partes: painel, poller e scripts. Exige reinstalar dependências (Gunicorn 23).

### Corrigido
- Poller sem `poller_state.json` (instalação nova, arquivo apagado) notificava todo pagamento da janela de 90 dias. Agora a primeira execução só grava a baseline.
- Falha na consulta de chamados reenviava, no ciclo seguinte, os avisos de fatura já enviados. O estado é gravado logo após as faturas.
- `poller_state.json` gravado de uma vez (temporário + troca); queda no meio não corrompe mais o arquivo.
- `poller_state.json` não cresce mais sem limite: faturas e chamados fora da janela são descartados.
- Bloqueio de login: a contagem zera quando o bloqueio vence ou após 5 min sem erro (antes, cada erro depois do primeiro bloqueio bloqueava de novo); IPs parados saem da memória.
- `acessos.log`: trava também entre processos (painel e poller).
- Erro de CSRF volta para a própria tela do painel, não para o `Referer`.
- `uninstall.sh` remove a configuração de domínio (site Nginx/Apache e ajuste do systemd).

### Segurança
- Cabeçalhos: `X-Frame-Options: DENY` e `frame-ancestors 'none'` (painel não abre em moldura de outro site), `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`; `Strict-Transport-Security` com domínio.
- Cookie de sessão com `SameSite=Lax` explícito.
- Gunicorn 23 (corrige CVE-2024-6827, request smuggling; relevante com proxy).

### Removido
- `usuario_e_admin` (sem uso nos templates) e parâmetro sem uso em `_acao_usuarios`.
- Textos antigos: "Logs" e "Configurações" (agora Histórico e Ajustes), caminho `server/aviso-broadcaster/`, comentário sobre Apache, "piloto" no README, eventos do poller no `install.sh` e no `.service`, seção 8 do README.

### Como atualizar o servidor
```bash
cd /opt/aviso-broadcaster && git pull
venv/bin/pip install -r requirements.txt
chown -R aviso-broadcaster: /opt/aviso-broadcaster
systemctl restart aviso-broadcaster
```

## [1.6.1] - 2026-10-16
Partes: painel e poller (timer).

### Corrigido
- Lentidão intermitente: o worker `sync` do Gunicorn atendia uma conexão por vez e travava o painel até 30 s numa conexão aberta sem pedido (pré-conexão do Chrome). Agora `gthread` com 4 threads, em 1 processo.
- Gravação concorrente: trava em `acessos.log` e `config.json`.
- `config.json` gravado num temporário e trocado de uma vez; o poller e o Gunicorn nunca leem o arquivo pela metade.

### Alterado
- Fonte: Manrope, a mesma do app, servida pelo painel (`static/fonts`, WOFF2, ~16 KB por peso). Sai o Google Fonts; nenhuma página depende de servidor externo.
- `controllr-poller.timer`: 1 hora (antes 10 min no repositório; o servidor já usava 1 hora). README e `install.sh` atualizados.

## [1.6.0] - 2026-10-16
Partes: painel e instalador.

### Adicionado
- `configurar-dominio.sh`: painel em `https://DOMINIO` com certificado Let's Encrypt e renovação automática (`certbot.timer`, testada com `--dry-run`).
  - Usa o Apache se estiver ativo; senão instala o Nginx.
  - Confere o DNS; libera 80/443 no `ufw` se ativo.
  - Remove o site se o certificado falhar.
  - `--remover` volta ao acesso por IP e porta.
- `install.sh` pergunta o domínio (opcional) e o e-mail do Let's Encrypt; sem domínio, acesso por `http://IP:PORTA`.
- Ajustes → Usuários → Editar: grupo, situação e nova senha (opcional) numa janela.
- Campo de senha com as regras marcadas enquanto se digita, Mostrar e Gerar (14 caracteres), no cadastro, na edição, em Minha senha e no primeiro acesso.
- Evento `usuario_editado` no Histórico (sem a senha).

### Alterado
- Novo usuário e edição não pedem mais a senha do administrador.
- Com domínio: Gunicorn escuta só em `127.0.0.1`; Ajustes mostra o endereço HTTPS e não troca a porta.
- Senha: máximo de 128 caracteres (painel e `install.sh`).
- Lista de usuários só para leitura; grupo e bloqueio saíram da linha e foram para Editar.

### Segurança
- Lista de IPs permitidos podia ser contornada com um `X-Forwarded-For` forjado. O cabeçalho agora só é aceito com `AVISO_BROADCASTER_PROXY=1` e de conexões locais, usando o último item.
- Trocar a senha (por Editar ou Minha senha) encerra as outras sessões do usuário.

## [1.5.0] - 2026-10-16
Partes: painel.

### Adicionado
- Grupos de usuários com permissões, em Ajustes → Grupos e permissões. Permissões: enviar aviso geral, gerenciar modelos, ver automáticos, alterar lembretes, ver histórico de eventos, ver notificações de clientes, alterar porta e IPs, gerenciar usuários e grupos.
- Grupo Administrador fixo, com todas as permissões e ao menos um usuário ativo.
- Criar grupo, inclusive copiando outro; excluir grupo sem usuários.
- Trocar o grupo de um usuário pela lista; bloquear e desbloquear usuário.
- Grupo na criação de usuário.
- Histórico registra: grupo criado/excluído, permissões alteradas, grupo do usuário alterado, usuário bloqueado/desbloqueado, IPs permitidos alterados.
- `permissoes.py`.

### Alterado
- Permissões conferidas no servidor em cada rota e ação (antes: só administrador × demais).
- Abas e botões aparecem conforme as permissões do grupo; o login leva à primeira aba permitida.
- Histórico entrega eventos e notificações de clientes só a quem tem a permissão correspondente.
- Ajustes: Usuários e Acesso e rede lado a lado; Grupos e permissões abaixo, na largura toda.
- Administrador pode ser removido, bloqueado ou movido por outro administrador, desde que reste um ativo.
- `install.sh` copia `permissoes.py` e grava o primeiro usuário no grupo Administrador.

### Segurança
- Sessão de usuário removido ou bloqueado é encerrada no próximo pedido (antes continuava válida até expirar).
- Usuário bloqueado não consegue entrar.
- A permissão de gerenciar usuários e grupos não pode ser dada a outros grupos.

### Migração
- Automática no primeiro carregamento: administradores → Administrador; demais → Atendimento (enviar, modelos, ver automáticos, histórico, notificações), sem mudança de acesso.
- `is_admin` continua gravado; voltar à 1.4.x mantém os administradores.

## [1.4.1] - 2026-10-16
Partes: poller.

### Corrigido
- Nome do cliente nas Notificações: `client_complete_name` no lugar de `client_name` (só o primeiro nome). Reserva: `client_name` + `client_lastname`.

## [1.4.0] - 2026-10-16
Partes: painel e poller.

### Adicionado
- Histórico → Notificações: um registro por aviso automático com data, tipo, cliente, CPF/CNPJ completo e conteúdo.
  - Pagamento confirmado: valor pago, data do pagamento, vencimento, contrato.
  - Cobrança de atraso: vencimento, valor, data de bloqueio.
  - Lembrete antecipado: dias até o vencimento, vencimento, valor, contrato.
  - Chamado respondido: protocolo, assunto.
  - Falha de envio: tipo e motivo.
- Contadores por tipo (verde, vermelho, âmbar, azul) e clientes avisados; filtram a lista ao clicar.
- Busca por nome, CPF com ou sem pontos, contrato ou protocolo. Período: hoje, 7 ou 30 dias.
- `envios_log.py` / `envios.log`: permissão 600, fora do git, retenção de 30 dias, gravação atômica.

### Alterado
- `acessos.log`: limite de 500 para 1000 eventos.
- `install.sh` copia `envios_log.py`.

## [1.3.0] - 2026-10-16
Partes: painel e poller. Lembrete de 2 a 7 dias exige app 2.5.3.

### Adicionado
- Aba Automáticos: último ciclo, próximo, falhas e avisos enviados no dia.
- Lembrete de vencimento: véspera (padrão), 2 a 7 dias antes ou desativado.
- Aviso de atraso desativável. Ao reativar, só atrasos novos são avisados.
- Janela de envio de lembretes e atrasos: padrão 08:00–20:00. Pagamento e chamado não são afetados.
- Troca de porta pelo painel: recarrega o Gunicorn (SIGHUP); porta 1024–65535 e livre.
- Selo de status no topo: ok, falhas (amarelo), parado (vermelho).
- Enviar: rascunho salvo no navegador; Ctrl+Enter abre a revisão.

### Alterado
- Visual: topo grafite com logotipo oficial; laranja só em ação e seleção.
- Enviar em três colunas (modelos, texto, prévia em tela de bloqueio).
- Modelos em cartões, edição em janela.
- "Logs" → Histórico; "Configurações" → Ajustes. Lembretes movidos para Automáticos.
- `install.sh` copia `lembretes.py` e `static/`.

### Compatibilidade
- Véspera: tipo `boleto_vence_amanha`, aceito por todas as versões do app.
- 2 a 7 dias: tipo `boleto_vence_em` (`dias`, `invoice_date_due`), ignorado por versões anteriores à 2.5.3. Manter a véspera até a 2.5.3 ser publicada.

## [1.2.1] - 2026-10-16
Partes: painel.

### Corrigido
- Enviar: modelo com texto longo gerava rolagem horizontal e desalinhava o formulário.
- Cartões "Últimos avisos" e "Notificações automáticas" desalinhados das colunas.

### Removido
- Menu lateral no computador (entrou na 1.2.0). Navegação só por abas no topo.

## [1.2.0] - 2026-10-16
Partes: painel.

### Adicionado
- Prévia da notificação (recolhida, aberta, no sino) e contadores de caracteres (80/500).
- Emojis por assunto (Rede, Horário, Status, Atendimento), lista em `painel_info.py`.
- Confirmação de envio em janela própria com a notificação exata (substitui `confirm()`).
- Últimos avisos enviados com "Usar de novo"; o log passa a guardar a mensagem.
- Cartão do poller: último ciclo, próximo, falhas em 24 h, alerta de parado.
- Logs com filtros (Avisos, Acessos, Poller, Falhas), etiquetas e hora relativa; ciclos vazios ocultos.

### Alterado
- Identidade do app: laranja #C94300, nome "Avisos HOTNET", menu da conta no topo.
- `install.sh` copia `access_log.py` e `painel_info.py`.

### Segurança
- Servidor recusa título acima de 80 e mensagem acima de 500 caracteres.

## [1.1.0] - 2026-10-16
Partes: poller. Sem reinício. App 2.5.2+ exibe a data; versões anteriores ignoram o campo.

### Adicionado
- Pagamento confirmado envia `invoice_date_credit` (data do pagamento, "Pago em" do app).

## [1.0.0] - 2026-09-04
Partes: painel e poller. Estado em produção desde o piloto.

### Adicionado
- Painel de avisos gerais (tópico `avisos_gerais`): Gunicorn, CSRF, usuários, modelos, logs, tema claro/escuro.
- Poller de avisos por conta (tópico `conta_<hash do CPF>`):
  - pagamento confirmado;
  - chamado respondido pela equipe;
  - fatura em atraso (uma vez por fatura);
  - boleto vence amanhã, com código Pix. Substitui o `VencimentoWorker` do app.
- `install.sh`, `uninstall.sh` e serviços systemd (`aviso-broadcaster`, `controllr-poller.timer`).

### Corrigido
- Primeira execução do poller só grava o estado inicial, sem notificar.
- `invoice_valid=false` é pagamento manual no escritório, não cliente inativo.
- Pagamento confirmado usa `invoice_amount_paid` em vez de `invoice_amount_document`.

[1.6.3]: https://github.com/jmanoelslva/AVISOS_APP_ANDROID_HOTNET/compare/v1.6.2...v1.6.3
[1.6.2]: https://github.com/jmanoelslva/AVISOS_APP_ANDROID_HOTNET/compare/v1.6.1...v1.6.2
[1.6.1]: https://github.com/jmanoelslva/AVISOS_APP_ANDROID_HOTNET/compare/v1.6.0...v1.6.1
[1.6.0]: https://github.com/jmanoelslva/AVISOS_APP_ANDROID_HOTNET/compare/v1.5.0...v1.6.0
[1.5.0]: https://github.com/jmanoelslva/AVISOS_APP_ANDROID_HOTNET/compare/v1.4.1...v1.5.0
[1.4.1]: https://github.com/jmanoelslva/AVISOS_APP_ANDROID_HOTNET/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/jmanoelslva/AVISOS_APP_ANDROID_HOTNET/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/jmanoelslva/AVISOS_APP_ANDROID_HOTNET/compare/v1.2.1...v1.3.0
[1.2.1]: https://github.com/jmanoelslva/AVISOS_APP_ANDROID_HOTNET/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/jmanoelslva/AVISOS_APP_ANDROID_HOTNET/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/jmanoelslva/AVISOS_APP_ANDROID_HOTNET/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/jmanoelslva/AVISOS_APP_ANDROID_HOTNET/releases/tag/v1.0.0
