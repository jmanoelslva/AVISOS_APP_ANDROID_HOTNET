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

[1.5.0]: https://github.com/jmanoelslva/AVISOS_APP_ANDROID_HOTNET/compare/v1.4.1...v1.5.0
[1.4.1]: https://github.com/jmanoelslva/AVISOS_APP_ANDROID_HOTNET/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/jmanoelslva/AVISOS_APP_ANDROID_HOTNET/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/jmanoelslva/AVISOS_APP_ANDROID_HOTNET/compare/v1.2.1...v1.3.0
[1.2.1]: https://github.com/jmanoelslva/AVISOS_APP_ANDROID_HOTNET/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/jmanoelslva/AVISOS_APP_ANDROID_HOTNET/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/jmanoelslva/AVISOS_APP_ANDROID_HOTNET/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/jmanoelslva/AVISOS_APP_ANDROID_HOTNET/releases/tag/v1.0.0
