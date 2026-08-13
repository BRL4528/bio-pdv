# bio-pdv — liberação por biometria no PDV

Substituir a digitação manual da senha do supervisor no PDV por um toque de dedo,
usando o módulo **Safran/IDEMIA MorphoSmart CBM** tirado de um relógio ponto.

## Como usar

**No Windows (produção):** baixe o `bio-pdv-setup.exe` da página de
**[Releases](https://github.com/BRL4528/bio-pdv/releases)** e dê duplo clique — sem
Python, sem terminal. Detalhes de instalação (tipos de PC, atalhos, auto-start)
em **[INSTALAR-WINDOWS.md](INSTALAR-WINDOWS.md)**.

Esse instalador é gerado e publicado automaticamente pelo GitHub Actions a cada
tag `vX.Y.Z` (build no `windows-latest`: PyInstaller + Inno Setup). Não precisa
de máquina Windows manual pra tirar uma release.

**Em desenvolvimento:**

```bash
pip install -r requirements.txt        # no Windows inclui pywin32 (DPAPI)

python app.py                          # bandeja + botão flutuante + gestão
python app.py --gestao                 # só a tela de gestão (máquina do admin)
python app.py --agente                 # só o agente do caixa
python app.py --porta COM3 --enter     # força a porta e manda Enter no fim
```

### Como chegar na interface

Ícone na bandeja (perto do relógio) — **um clique abre a gestão**, botão direito
abre o menu. Na primeira execução, com o cofre vazio, a tela abre sozinha. Depois
de instalado no Windows, há também atalho no Menu Iniciar e na área de trabalho.

No caixa: o operador clica na **bolha azul** (ou tecla `Ctrl+Alt+B`), o supervisor
encosta o dedo, o agente digita a senha no campo em foco. A bolha muda de cor:
azul (pronta) → amarelo (lendo) → verde (liberado) / vermelho (negado).

### Por que ninguém precisa saber a senha

Como o agente **digita** a senha, ela pode ser uma string aleatória que nem o
supervisor conhece. Isso mata o problema real do varejo: supervisor que entrega a
senha pro caixa pra não ter que levantar. Sem senha memorizável, não há o que
compartilhar — e a auditoria passa a valer alguma coisa.

### Arquivos gerados

| Arquivo | Onde | O quê |
|---|---|---|
| `cofre.json` | `%APPDATA%\bio-pdv` / `~/.config/bio-pdv` | índice biométrico → senha do PDV |
| `auditoria.jsonl` | idem | quem liberou o quê, quando, em que máquina |

No Windows as senhas são cifradas com **DPAPI**, amarradas à conta do Windows
daquela máquina — copiar o arquivo pra outro PC não serve de nada. **Fora do
Windows, o cofre é só base64 (ofuscação, não criptografia).** A auditoria nunca
grava senha.

## Estrutura

```
app.py                 entrada: bandeja, atalho global, orquestração
biopdv/reader.py       driver do CBM (ILV sobre serial) — sem dependência de GUI
biopdv/vault.py        cofre índice→senha (DPAPI no Windows)
biopdv/audit.py        trilha de auditoria append-only (JSON Lines)
biopdv/inject.py       digitação via SendInput (Unicode, independe de layout)
biopdv/worker.py       QThread: operação bloqueante sem travar a interface
biopdv/manager.py      tela de gestão (cadastrar/listar/excluir/auditoria)
biopdv/agent.py        botão flutuante que não rouba foco + fluxo de liberação
```

## Os dois detalhes que fazem funcionar

**1. A janela flutuante não pode roubar o foco.** Se roubar, o campo de senha do
PDV perde o cursor e a digitação vai pro vazio. Resolvido com
`Qt.WindowDoesNotAcceptFocus` + `Qt.Tool` + `Qt.WindowStaysOnTopHint`
(equivale a `WS_EX_NOACTIVATE` no Windows).

**2. Digitar, não colar.** `Ctrl+V` deixaria a senha no histórico da área de
transferência (`Win+V`), e muitos PDVs bloqueiam colar em campo de senha. O
`inject.py` usa `SendInput` com `KEYEVENTF_UNICODE`, que injeta pelo código do
caractere e portanto independe do layout (ABNT2, US, etc.).

⚠️ **UIPI:** se o PDV roda como administrador, o agente também precisa rodar como
administrador — senão o Windows bloqueia o `SendInput` entre níveis de integridade
diferentes. O agente detecta e avisa.

## O módulo (confirmado na etiqueta)

```
SAFRAN Morpho          UL/cUL ITE E205978   FCC   CE   RoHS
Model : MSO CBM
P/N   : 293652806
S/N   : 17191006B14
Date  : 1719-A04
IN    : 3-5.5V --- 500mA          Made in INDIA
```

Confere com o datasheet SAGEM do CBM e com o guia oficial de instalação:

| Item | Valor |
|---|---|
| Interfaces | **conector de 8 pinos, USB *e* Serial** |
| Serial | UART (RX-TX), **Open Collector até 5 V**, 9.600–115.200 bps, *software handshake*, só TxD/RxD/GND |
| USB | USB 2.0 *full speed* (12 Mbit/s), classe **CDC** |
| Alimentação | 3–5,5 V. Sensor ligado: **300 mA máx @ 5 V**. Sensor desligado: 100 mA. Standby: 500 µA |
| Sensor | óptico 500 dpi, 8 bits/px, área ativa 14×22 mm, IP65 |
| CPU | núcleo ARM9 |
| Desempenho | verificação < 0,8 s, identificação < 1 s |

O `MSO CBM` é o módulo OEM que vive dentro dos MSO1200/1300/1350 — daí o
`PID 0x0047` nomeado "CBM OEM" no pyMorphoILV.

## Decisão de arquitetura

O ESP32 foi **cortado do projeto**. Motivos:

| Bloqueio | Detalhe |
|---|---|
| ESP32 WROOM não tem USB | A porta do DevKit é um bridge CP2102/CH340. Não é USB host (não lê o leitor) nem USB device (não vira teclado). Sobraria BLE HID — pareamento frágil num caixa. |
| O CBM já faz o matching | Coder/matcher MINEX embarcado, base interna de templates e busca 1:N em < 1 s. O "comparar biometria" que ia virar mil `if` no ESP **não existe**: manda IDENTIFY, ele responde qual usuário é. |
| O PC já está lá | O PDV roda no PC e o leitor pode ir direto nele. O ESP só somava dois problemas sem resolver nenhum. |

**Desenho final:** módulo CBM → USB → PC do caixa → agente local em Python que
identifica o dedo e injeta a senha no campo em foco (`SendInput` no Windows).

## A descoberta que destrava tudo

O CBM se apresenta como **CDC-ACM** — uma porta serial comum. Confirmado no
handshake do [pyMorphoILV](https://github.com/alromh87/pyMorphoILV):
`SET_LINE_CODING` a **38400 8N1**, endpoints OUT `0x02` / IN `0x83`.

- **VID `0x079B`** (Sagem/Safran/Morpho/IDEMIA)
- **PID `0x0047`** = CBM OEM ← este módulo
- PID `0x0024` = MSO 300

Consequência: no Windows ele vira um `COM3` pelo `usbser.sys` nativo e no Linux
um `/dev/ttyACM*`. **Não precisa do SDK licenciado da IDEMIA** — fala-se ILV
direto por pyserial. O mesmo protocolo roda nos pinos TTL do módulo.

O guia oficial confirma, palavra por palavra: *"The integrated USB driver of the
MorphoSmart terminal emulates a RS232 serial port. The MorphoSmart terminal is
processed as a Communication Device Class (CDC)"*. E o datasheet chama a serial de
*"open 'Morpho Host Interface' protocol"* — aberto, não sob NDA.

### Documentos que resolvem o que falta

Nenhum dos dois é público; **quem tem é o fabricante do relógio ponto**:

| Documento | Referência | O que resolve |
|---|---|---|
| MorphoSmart **CBM Module Integration** | `SSE-0000077475` | Pinagem dos 8 pinos + o *sample of electric interface* (o circuito adaptador com o pull-up) |
| MorphoSmart **Host System Interface Specification** | `.chm`, junto ao SDK | Layout dos comandos ILV: `IDENTIFY`, `Add_Record`, `ID_Matching_Strategy` |
| Projeto **MSO ILV_Sample** | vem no SDK | **Código C funcional** montando os comandos ILV — atalho pra fase 3 |

## Protocolo ILV

Enquadramento:

```
"SYNC" | size:u32le | ~size:u32le | payload | "EN"
```

Payload é um ILV: `id:u8 | len:u16le | value[len]`. Se `len == 0xFFFF`, o
tamanho real vem nos 4 bytes seguintes.

**Pegadinha:** ILV **aninha**. Em comandos como IDENTIFY, os 6 primeiros bytes do
value são status + índice, e o que vem depois é um ILV *filho* dentro do value do
pai — não um irmão. Ver `walk_nested()`.

Comandos mapeados: `0x05` GET_DESCRIPTOR, `0x21` ENROLL, `0x22` IDENTIFY,
`0x30` CREATE_DB, `0x33` DELETE_DB, `0x3D` EXPORT_IMAGE, `0x71` ASYNC_MESSAGE.

Status: `0x01` HIT, `0x02` NO_HIT, `0x04` DB_FULL, `0x05` DB_EMPTY,
`0x22` FAKE_FINGER, `0x23` MOIST_FINGER.

## Fases

- [x] **0. Protocolo** — `morpho_ilv.py`, enquadramento validado byte-a-byte
      contra o pyMorphoILV.
- [x] **0b. Identificação** — etiqueta lida: `MSO CBM`, P/N `293652806`. É Morpho
      mesmo, logo o ILV se aplica.
- [x] **1. Fiação** — RESOLVIDA 2026-08-06/07. O harness usa **USB**. Os 8 fios:
      2 pretos=GND, 2 vermelhos=VBUS, azul+amarelo=UART (não usados),
      **branco=D− e verde=D+** (código de cor USB). O par USB vinha **soldado um no
      outro** dentro do espaguete termo-retrátil (curto D+/D− = SE1 = os 68 `-71`).
      Dessoldar o branco do verde e ligar `verde→verde, branco→branco,
      vermelho→VBUS, preto→GND` num plug USB. Enumera `079b:0047`.
- [x] **2. Link** — GET_DESCRIPTOR responde (2026-08-07). Ver "Enumerar no Linux".
- [x] **3. IDENTIFY/ENROLL** — RESOLVIDO 2026-08-07. Layouts do SDK oficial;
      `bio.py` faz enroll e identify com feedback ao vivo do sensor.
- [x] **4. Cadastro** — funcionando. `bio.py enroll --user <nome>` grava na base
      embarcada e sorteia a senha; `bio.py identify` devolve a senha. Validado.
- [x] **5. Agente** — FEITO 2026-08-07. Botão flutuante sem roubo de foco +
      atalho global `Ctrl+Alt+B` → identify → `SendInput` no campo em foco.
      Senhas via DPAPI. Falta validar em Windows real com o PDV.
- [x] **6. Auditoria** — `auditoria.jsonl`, aba própria na tela de gestão.
- [ ] **7. Autorização remota** (Fase 2) — leitor na mesa do supervisor. Regra de
      ouro: **a senha nunca trafega na rede**; o lado remoto só devolve
      "aprovado por Fulano às 14h32" e quem digita é o agente do caixa.

## Enumerar no Linux (o CDC-ACM nativo recusa este módulo)

O descritor USB do CBM é fora de norma; o `cdc_acm` do kernel recusa com
`Zero length descriptor references ... probe failed with error -22`. Contorno com
o driver serial genérico (uma vez por boot, precisa de root):

```bash
sudo modprobe usbserial
echo "079b 0047" | sudo tee /sys/bus/usb-serial/drivers/generic/new_id
sudo chmod 666 /dev/ttyUSB0      # ou adicionar o usuario ao grupo dialout
python3 probe.py --port /dev/ttyUSB0
```

Cria `/dev/ttyUSB0`. GET_DESCRIPTOR devolve: Product `CBM`, licenças
**`MSO_WSQ;MSO_IDENTPLUS`**, Mobi5 S/N `17149F03017`, MSO OEM S/N `1719I006814`,
OEM Product ID `293652806`, flash 4096 kb, MSO Version `13.02.b-C`.

## Protocolo — RESOLVIDO (2026-08-07)

**A fonte definitiva é o SDK Linux oficial da Sagem/Morpho em C, público no GitHub:
[Senthamilarasi/MSOlinuxDistrib-1.3](https://github.com/Senthamilarasi/MSOlinuxDistrib-1.3).**
Não precisa de licença, SDK pago, captura USB no Windows nem doc do fabricante do
relógio ponto. Todos os layouts abaixo saíram de lá (a `libMSO`, que fala com o
hardware de verdade).

### A pegadinha que custou meia sessão: `0xF4` NÃO é "base inexistente"

`0xF4` = **`ILVERR_CMD_INPROGRESS`** — "comando recebido enquanto outro está
rodando". Base inexistente seria `0xF7`. Um IDENTIFY/ENROLL anterior fica pendente
capturando até o timeout e **bloqueia todos os comandos seguintes**, que passam a
devolver `0xF4` uniformemente — parece parede, é só fila suja.

> **Sempre mandar `CANCEL` (`0x70`, value vazio → frame `70 00 00`) antes de cada
> comando.** É o que o SDK oficial faz. Cancel não tem resposta própria; o comando
> pendente responde `0xE5` (abortado). `bio.py` já faz isso sozinho.

Formato de erro: `id | L | [status:u8][erro_interno:i32le]`. O **status** é o código
acionável; o i32le é diagnóstico (a faixa -330..-345 é interna da aplicação
embarcada; `-334` não tem nome público e é irrelevante).

### Layouts (todos com base index = 0)

```
CANCEL          0x70 | 00 00 | (vazio)
GET_BASE_CONFIG 0x07 | 01 00 | [base:u8]
   resposta V: [st u8][dedos u8][max u32][atuais u32][livres u32][ncampos u32]...

IDENTIFY        0x22 | L | [base u8][timeout_s u16le][threshold u16le][qualidade u8]
   + opcional aninhado: 34|04 00|mask:u32le   (eventos)  /  56|01 00|01 (score)
   threshold = nível FAR 0..10, recomendado 5. Value fixo tem 6 bytes (≠6 → 0xFE).
   resposta V: [st][resultado][índice u32le] + 04|len|user_id ...

ENROLL          0x21 | L | [base u8][timeout_s u16le][qualidade u8][tipo u8]
                           [dedos u8][grava u8][exporta u8]
   + aninhado: 04|len|user_id (C-string COM o NUL)  /  34|04 00|mask
   tipo: 0 = três aquisições por dedo, 1 = uma. grava=1 salva na base embarcada.
   resposta V: [st][enroll_status][índice u32le]

CREATE_DB       0x30 | 05 00 | [base u8][flash u8=0][max u16le][dedos u8]
```

### Eventos assíncronos (`0x71`) — feedback ao vivo do sensor

Pedidos via ILV aninhado `34 | 04 00 | mask:u32le` (bit0=1 comandos de dedo,
bit1=2 imagem, bit2=4 progresso de enroll). Chegam intercalados, **o host não
responde nada**, é só ler até vir o frame com o id do comando original.

`71 | L | [st u8][tipo u8][len u16le][payload]`

- **tipo 1** → `i32le`: 0=sem dedo, 5=pressione mais, 7=remova o dedo, **8=captura OK**
- **tipo 4** → 4 bytes `[dedo, total_dedos, captura, total_capturas]`

### Estado real do módulo (lido em 2026-08-07)

```
dedos/registro=2  capacidade=5000  cadastradas=188  livres=4812  campos=0
```

⚠️ **As 188 são digitais de terceiros herdadas do relógio ponto** (dado pessoal
sensível, LGPD). `bio.py` só adiciona; nunca apaga nem exporta. Não rodar
`ERASE_BASE` (`0x32`) nem `DESTROY_DB` (`0x3B`).

### Validado ponta a ponta

ENROLL de 3 capturas → índice 9 → IDENTIFY → HIT no índice 9 → senha recuperada.

**Ferramentas:** `bio.py` (status/enroll/identify/list/forget) é a ferramenta boa.
`fuzz_identify.py` foi a sonda de engenharia reversa — não é mais necessária.

## Fiação

O datasheet confirma: **conector de 8 pinos carregando USB *e* Serial**. O harness
do relógio ponto condensa essas 8 vias em **4 fios** (preto, vermelho, azul,
amarelo) — e 4 condutores servem para as duas interfaces (`VBUS/D−/D+/GND` ou
`VCC/GND/TX/RX`). **Qual das duas o integrador usou ainda não está determinado.**

Teste que decide, sem energia, multímetro em resistência:

| Leitura | Conclusão |
|---|---|
| ~1,5 kΩ de um sinal pro VCC | É **USB** — pull-up de *full speed* do lado device. Solda num plug USB e o SO entrega `079B:0047`. Sem pull-up, sem baudrate, sem adaptador. |
| Alta impedância nos dois sinais | É **serial TTL** — siga o esquema abaixo. |

Antes disso, mapeie por continuidade quais 4 das 8 vias o harness usou.

### Identificar o VCC sem a placa do relógio ponto

A placa original não está mais disponível, então não dá pra medir 5 V no harness.
Testes válidos, em ordem de confiabilidade:

1. **Capacitância** (modo `F`/`µF`), ponta preta no fio preto (GND): o **VCC** dá
   centenas de nF a dezenas de µF (capacitores de desacoplamento); linha de dados
   dá poucos pF ou nada. Diferença de ordens de grandeza.
2. **~1,5 kΩ entre o VCC candidato e um sinal** → confirma o VCC *e* identifica o
   **D+** de uma vez.
3. Sem modo capacitância: resistência na escala mais alta, observando o
   *comportamento* — no VCC o valor **sobe devagar** (carregando os capacitores);
   num pino de dados salta direto pra um valor estável.

**Modo diodo NÃO serve.** Todo pino de CI tem diodos de proteção ESD pro GND, então
qualquer fio lê ~0,7–0,8 V. Medições reais nesta unidade: preto↔vermelho `0,806 V`,
preto↔azul `0,830 V` — indistinguíveis, como esperado. Não conclua nada disso.

**Resultado nesta unidade** (multímetro Minipa ET-1000, `Ω` em `2000K` — nenhum dos
dois multímetros da bancada tem capacitância):

- `preto` = **GND** — continuidade com a blindagem metálica do módulo
- `vermelho` = **VCC** — leitura sobe gradativamente (carga dos capacitores)
- `azul` / `amarelo` = par de dados, posição a determinar por tentativa

**Confirmado energizando** (fonte de bancada Wanptek NPS3010W): `4,99 V / 23 mA /
modo C.V.`. Módulo vivo, sem limitação de corrente — polaridade invertida teria
batido em C.C. Os 23 mA correspondem ao ARM9 inicializado e ocioso, sem host
conversando e com o sensor apagado (datasheet: 500 µA standby, 100 mA sensor off).

Com o par de alimentação identificado, **não há mais passo irreversível no projeto**:
inverter os fios de dados não danifica nada.

> Ao ligar os dados, use **fonte única pelo USB** — não alimente pela bancada com o
> VBUS também ligado (dois 5 V brigando). O módulo usa a presença do VBUS pra saber
> que há um host; sem ele pode não habilitar o pull-up do D+ e nunca enumerar.

### Se for USB (caminho curto)

É o caminho oficial: o MSO1300 é este módulo numa carcaça com cabo USB. Solde os 4
fios num plug USB-A (`1=VBUS 2=D− 3=D+ 4=GND`) e o driver CDC nativo faz o resto.

Identificação de GND com risco zero: continuidade do **fio preto contra a
blindagem metálica** do módulo — a lata é aterrada.

O que é inofensivo e o que não é:

- **Dados trocados (D+/D−): inofensivo.** O host tem pulldown de 15 kΩ; não
  enumera e nada queima. Inverta e tente de novo.
- **VCC/GND invertido: mata o módulo.** Único passo irreversível do projeto.

Portanto **não descubra qual sinal é qual — teste as duas posições.** São duas
tentativas de 30 s: `azul→D−, amarelo→D+` e depois invertido. Use jumper ou garra
jacaré, **solde só depois** de ver o `079b:0047`.

Atalho opcional: ~1,5 kΩ entre um sinal e o VCC identifica o **D+** (pull-up de
*full speed*, só existe no D+). Vale só quando dá positivo — se o pull-up for
interno ao controlador, não aparece com o módulo desenergizado.

Primeira energização com rede de proteção — medidor USB inline e um hub velho, não
a porta da placa-mãe:

| Corrente | Diagnóstico |
|---|---|
| ~100 mA estável | polaridade certa, módulo vivo (sensor desligado) |
| ~0 mA | fios de dados errados, nada queimou |
| salta pra 500 mA+ / porta desliga | curto ou polaridade invertida — tire já |

Confirmação: `dmesg -w` numa aba antes de plugar, depois `lsusb | grep 079b`.
Alvo: `079b:0047`.

### Se for serial TTL

O ILV é o mesmo protocolo nos dois meios; só muda o meio físico.

```
  CBM            adaptador USB-TTL (CP2102/FTDI)
  ----           -------------------------------
  preto   GND ─────────── GND        (obrigatório: GND comum)
  vermelho VCC ─┬───────── 5V do USB  (NÃO do regulador do adaptador)
  amarelo  TX ──┼──[4k7]──┘          ← pull-up: saída é OPEN-COLLECTOR
           TX ──┴───────── RX
  azul     RX ──────────── TX        (sempre cruzado)
```

**Três armadilhas, na ordem em que elas te pegam:**

1. **Open-collector.** O datasheet diz `UART (RX-TX), Open Collector up to 5V`, e o
   guia oficial é explícito: *"the electrical levels are 'TTL open collector' and
   are not compliant with V.24 recommendation. **Electrical adapter is
   mandatory.**"* A saída só puxa pra baixo, não gera nível alto. Sem o pull-up de
   4k7 do TX pro VCC de lógica você vê silêncio ou lixo e culpa o baudrate. No
   relógio ponto esse pull-up estava **na placa dele** — saiu junto com o módulo.
   O circuito de referência está no `SSE-0000077475`.
2. **Alimentação.** 300 mA máx @ 5 V com o sensor ligado (a etiqueta declara 500 mA);
   o regulador 3,3 V de um breakout FTDI entrega ~100 mA. Alimente do 5 V do USB ou
   de fonte externa, senão o módulo reseta no meio da captura.
3. **Nunca adivinhe VCC/GND.** Inverter mata o módulo. Identifique medindo o
   conector na placa do relógio ponto **energizada e com o módulo desconectado**:
   VCC = tensão firme; GND = 0 V com continuidade pro chassi; TX/RX repousam perto
   do VCC, e o que oscila é o TX da placa (vai no RX do adaptador).

Confirme se a lógica é 5 V ou 3,3 V — define o pull-up e se o adaptador precisa de
level shifter.

Trocar TX/RX por engano não queima nada, então `--scan-baud` com os dois sentidos é
um teste seguro.

### O que falta descobrir na fase 3

O pyMorphoILV **implementa o parser** da resposta do IDENTIFY, mas não o
montador da requisição — só `getInfo`, `getFingerPrint` (captura de imagem),
`createDB` e `deleteDB`. O layout exato dos parâmetros do `0x22` sai de:

1. *MorphoSmart Host System Interface Specification* (`.chm`) — documento da
   IDEMIA que **o fornecedor do relógio ponto tem**, foi o que ele usou; ou
2. o projeto **`MSO ILV_Sample`** que vem no SDK: *"A sample of development of this
   protocol, with C language source files, is provided with the MorphoSmart SDK
   package"*. É código funcional montando os comandos — o atalho real; ou
3. empiricamente, por analogia com o `0x21` e o retorno `INVALID_COMMAND` (`0x50`)
   como sinal de "chegou, mas não entendi" — o `--raw` do probe existe pra isso.

## Uso

```bash
python3 probe.py --list                          # lista portas / diagnostica
python3 probe.py --port /dev/ttyUSB0             # GET_DESCRIPTOR (via TTL)
python3 probe.py --port /dev/ttyUSB0 --scan-baud # varre baudrates
python3 probe.py --port COM4 --raw 05:01:00:2f   # ILV cru
python3 probe.py --port COM4 --monitor           # só escuta (evento assíncrono)
```

Na via TTL o autodetect por VID **não funciona** (o adaptador tem VID próprio) —
passe `--port` sempre.

Dependência: `pyserial`. Linux: usuário no grupo `dialout`.

Testado sem hardware contra um CBM emulado em par de PTYs (socat): round-trip de
frame, parse de ILV aninhado e caminho de erro de porta. O enquadramento confere
byte-a-byte com o pyMorphoILV, mas **nada foi validado contra o silício ainda**.

## Atualização automática (GitHub Releases)

Aba **Atualizar** na tela de gestão: verifica, mostra o que mudou e pergunta
antes de instalar. Nada é instalado sem alguém clicar.

### Publicar uma versão nova

Normal: **bump a versão e tageia** — o resto é automático.

```bash
# 1. bump em biopdv/__init__.py -> __version__ = "1.2.0"
git commit -am "Versão 1.2.0"
git tag v1.2.0 && git push --tags
```

O workflow `.github/workflows/release.yml` builda numa runner `windows-latest`
(PyInstaller → `.exe`, Inno Setup → `bio-pdv-setup.exe`) e publica a release com
os três arquivos: `bio-pdv-setup.exe` (o que uma pessoa baixa e instala),
`bio-pdv-<v>-windows.zip` e `manifest.json` (consumidos só pelo auto-updater
interno).

Manual, se a Action falhar ou você quiser gerar localmente:

```bash
# build-windows.bat                (gera dist/bio-pdv/)
# compile instalador.iss no Inno Setup -> Output/bio-pdv-setup.exe
python publicar-release.py 1.1.0 --notas "Corrige a digitação no Windows"
```

O script zipa o `dist/`, calcula o SHA-256, escreve o `manifest.json` e publica
tudo via `gh` CLI (inclui `Output/bio-pdv-setup.exe` se existir — ou passe
`--instalador caminho\bio-pdv-setup.exe`). Sem o `gh` instalado, ele para e
mostra o que subir à mão.

⚠️ **O zip e o manifest são obrigatórios na release** — sem eles o app
**recusa** a atualização automática, pois é do manifesto que sai o hash. O
instalador é o que importa pra quem só quer baixar e instalar do zero. E o
`__version__` do código tem que bater com a tag, senão o script aborta: é por
ele que os caixas sabem em que versão estão.

### Modelo de confiança — o que protege e o que não

| Proteção | Contra o quê |
|---|---|
| HTTPS obrigatório (recusa `http://`) | alguém na rede trocar o pacote no meio do caminho |
| SHA-256 conferido antes de instalar | download corrompido ou truncado |
| Downgrade recusado | forçar a volta a uma versão com falha conhecida |
| Checagem de *zip slip* | pacote que tenta escrever fora da pasta de instalação |

**O que NÃO protege:** o hash vem do manifesto, baixado da mesma origem. Quem
controlar a conta do GitHub controla todos os caixas — e este app digita a senha
do supervisor. **Ligue 2FA nessa conta**; é o elo real da corrente.

Se usar repositório privado, o token vai num PC de caixa e pode ser extraído de
lá. Prefira release pública, ou um token somente-leitura restrito a este repo.

### Por que a troca é feita por um `.bat`

O Windows trava o `.exe` em execução — não dá para sobrescrevê-lo de dentro do
próprio programa. O `updater.py` escreve um `.bat` que espera este processo
morrer (pelo PID), copia por cima com `robocopy` e reabre o app.

## Segurança

Override de supervisor em PDV (cancelamento, desconto, sangria) é exatamente o
evento que auditoria quer rastreado. Digital que só datilografa uma senha fixa
não deixa rastro de quem foi — por isso a fase 6. A senha é cifrada com DPAPI,
nunca em texto puro no disco, e a auditoria nunca grava senha.

### Limitação conhecida: o agente não valida o destino

⚠️ **O agente digita a senha em qualquer coisa que estiver em foco.** Ele não
verifica se a janela é a do PDV nem se o controle é campo de senha. Se alguém
acionar a bolha com o Notepad aberto, a senha aparece na tela em texto puro.

A mitigação hoje é procedimental: **a liberação exige uma ação deliberada**
(clique na bolha ou `Ctrl+Alt+B`) — não dispara sozinha ao encostar o dedo. Foi
por isso que se descartou o modo "sempre armado", que seria mais cômodo e bem
mais perigoso.

Endurecimento pendente, em ordem de valor:

1. Comparar o título da janela em foco com uma lista de janelas permitidas
   (o campo `janela` já é gravado na auditoria justamente para levantar essa lista).
2. No Windows, checar via `GetGUIThreadInfo` + `WM_GETPASSWORDCHAR` se o controle
   em foco é mesmo campo de senha.
3. Recusar a digitação se o foco mudar entre o acionamento e a resposta do leitor.
