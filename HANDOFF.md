# Contexto de continuidade — bio-pdv

Retomada de uma sessão anterior (2026-08-05). Leia este arquivo e o `README.md`
antes de agir. O README tem o detalhe técnico; este aqui tem o **estado** e o
**próximo passo**.

## Objetivo

No PDV interno, quando o sistema pede a senha do supervisor, o supervisor encosta
o dedo num leitor e a senha é preenchida. Nada de digitar.

## Hardware (confirmado fisicamente, não suposto)

Módulo **Safran/IDEMIA MorphoSmart CBM** tirado de um relógio ponto:

```
Model : MSO CBM        P/N : 293652806
S/N   : 17191006B14    IN  : 3-5.5V --- 500mA
```

Conector de 8 pinos do módulo (USB **e** Serial) condensado pelo harness do
fabricante em **4 fios**, já identificados por medição:

| Fio | Função | Como foi confirmado |
|---|---|---|
| preto | **GND** | continuidade com a blindagem metálica |
| vermelho | **VCC** | resistência sobe gradativamente (carga dos capacitores) + energizado com sucesso |
| azul | dado | — |
| amarelo | dado | — |

Energizado em fonte de bancada: **4,99 V / 23 mA / modo C.V.** → módulo vivo,
polaridade correta, sem curto.

O usuário tem: fonte Wanptek NPS3010W (com limite de corrente), multímetro Minipa
ET-1000 (**sem modo capacitância**), adaptador USB-TTL, protoboard.

## Decisões tomadas — NÃO reabrir

1. **O ESP32 foi cortado do projeto.** A ideia original era o ESP ler a digital e
   digitar a senha como teclado USB. Inviável: o ESP32 WROOM não tem controlador
   USB nenhum (a porta do DevKit é bridge CP2102/CH340) — não é host nem device.
   Além disso o CBM já faz matching embarcado, então não há lógica de comparação
   pra escrever em lugar nenhum.
2. **Arquitetura final:** módulo → PC do caixa → agente local em Python que
   identifica o dedo e injeta a senha no campo em foco (`SendInput` no Windows).
   O usuário tem acesso livre pra instalar software no PC do PDV.
3. **Não precisa do SDK licenciado da IDEMIA.** O CBM é CDC-ACM (porta serial
   comum, 38400 8N1) e o protocolo ILV foi reimplementado do zero em
   `morpho_ilv.py`.

## Estado do código

- `morpho_ilv.py` — protocolo ILV completo (enquadramento, parser com aninhamento,
  status, decoder do IDENTIFY). Enquadramento validado **byte-a-byte** contra o
  pyMorphoILV.
- `probe.py` — sonda de bancada: autodetecção por VID, `--scan-baud`, `--raw`,
  `--monitor`.
- Testado **sem hardware** contra um CBM emulado em par de PTYs (socat): round-trip
  de frame, ILV aninhado, caminhos de erro. **Nada foi validado contra o silício
  ainda.**

## 🔴 RESOLVIDO 2026-08-05 17:20 — NÃO É USB, É A SERIAL TTL

**A pergunta "USB ou TTL?" está fechada: é TTL.** Toda a análise de USB abaixo
(inclusive a fase 1 "confirmada") estava investigando o transporte errado.

### A medição que decidiu

Com o módulo **plugado no host USB** (portanto com o pull-down de 15 kΩ do host
aplicado em cada linha), medido com o contato do conector já consertado:

| Fio | Medido | Impedância implícita | Leitura |
|---|---|---|---|
| azul | **3,76 V** | `3,76 = 5×15k/(R+15k)` → **R ≈ 4,95 kΩ** | pull-up de **4k7** |
| amarelo | **5,00 V** | R ≈ 0 | trilho de 5 V **ou saída drivada** |

O `4,95 kΩ` casa com o **4k7** que o datasheet exige pro open-collector
(`UART (RX-TX), Open Collector up to 5V`). E o critério do `README` linha 226 —
*"TX/RX repousam perto do VCC"* — está satisfeito literalmente.

**O que os números excluem:**

- Pull-up USB de 1,5 kΩ pra 3,3 V leria **3,0 V**. Nenhuma linha dá isso.
- Open-collector *sem* pull-up seria arrastado a ~0 V pelos 15 kΩ. O azul não foi.
- **Duas linhas altas ao mesmo tempo é SE1 — estado ILEGAL em USB.**

### Por que 68 tentativas falharam, e por que inverter nunca mudou nada

O host via **SE1** num par que nunca foi USB. Isso reinterpreta o achado central da
sessão anterior: *"erro que não muda ao inverter os dados não é erro de pinagem"* —
observação correta, **inferência errada**. Não sobrava falha elétrica; as duas
orientações apresentam nível alto na posição do D+ porque as duas linhas são de um
**UART ocioso**. Inverter não podia mudar nada.

Becos sem saída, agora fechados: integridade do par diferencial e queda de VBUS no
inrush. **Não havia par diferencial.** Não gaste mais tempo nisso.

### A leitura antiga (2,89 V / 1,86 V) não era lixo de voltímetro — era atenuada

O mau contato metia resistência em série e derrubava as duas leituras. O handoff
antigo descartou esses números como "voltímetro de 10 MΩ lê lixo num pino
flutuante". Estava errado: eram os mesmos níveis, atenuados. **Consertar o contato
não fez o módulo funcionar — fez a medição virar confiável, e foi isso que destravou
o diagnóstico.**

### AMBIGUIDADE QUE SOBROU — resolver primeiro, 30 segundos

O amarelo em 5,00 V com impedância ~0 tem duas leituras:

- **(A) É o TX do módulo, drivado, em repouso alto.** Saída push-pull lê o trilho
  cheio contra 15 kΩ. Se for isso, **o firmware está VIVO** — push-pull idle-high
  exige o periférico UART inicializado; MCU morto ou em reset deixa o pino como
  entrada. Derruba a nota "não há evidência de processador rodando".
- **(B) O amarelo está amarrado no trilho VCC** e não é sinal. Aí o módulo pode
  seguir morto e o par serial real é outro.

**Teste, sem energia, `Ω` na escala alta, ponta preta no fio VERMELHO (VCC):**

| Leitura no amarelo | Conclusão |
|---|---|
| perto de 0 Ω | **(B)** — amarelo é VCC, não é sinal |
| aberto / alta | **(A)** — saída drivada, módulo vivo |

O azul deve dar ~4k7 nos dois casos.

### Montagem TTL se der (A) — duas correções ao README

```
preto    GND  ─────────── GND do adaptador
vermelho VCC  ─────────── 5 V do USB     (NÃO o regulador do adaptador)
amarelo  TX   ─────────── RX do adaptador
azul     RX   ─────────── TX do adaptador   (sempre cruzado)
```

1. **O pull-up de 4k7 provavelmente é dispensável.** Se o amarelo é drivado em 5 V
   ele já gera nível alto sozinho — a armadilha nº 1 do README, que custou a sessão
   passada, pode não se aplicar mais.
2. **Conferir o nível lógico do adaptador.** A lógica é **5 V**; CP2102/FTDI é 3,3 V.
   Jumper de VCCIO em 5 V, ou level shifter no RX, senão é lixo (ou dano).
3. **Medir VCC no módulo durante o teste** (vermelho↔preto, 4,5–5,2 V) — furo nº 1,
   ainda aberto, agora com motivo concreto: o módulo pede até 300 mA e o regulador
   3,3 V de um breakout entrega ~100 mA.

Depois: `python3 probe.py --scan-baud` e, no silêncio, **repetir com amarelo/azul
trocados** (furo nº 2, nunca rodou).

### ⚠️ Parar de plugar no USB

Se o amarelo é 5 V de baixa impedância e estava no D+ (verde), isso injeta 5 V num
PHY de 3,3 V. ~70 plugadas sem dano aparente, mas não há mais motivo pra arriscar.

---

## ATUALIZAÇÃO 2026-08-05 17:13 — O CONTATO NÃO ERA A CAUSA

O usuário descobriu que **azul e amarelo estavam sem contato** no conector e
consertou. Retestado em seguida, nas duas orientações:

| Hora | Ligação | Host anuncia | Resultado |
|---|---|---|---|
| 17:10 | amarelo → branco (D−) | `low-speed` | `-71`, 4 tentativas |
| 17:13 | amarelo → verde (D+) | `full-speed` | `-71`, 8 tentativas |

**Duas conclusões, uma boa e uma ruim:**

1. ✅ **Orientação confirmada pela 3ª vez** (15:46, 15:58, 17:13), agora com contato
   bom. `amarelo→verde, azul→branco` é definitivo. **Não mexer mais.**
2. ❌ **O conserto do contato não mudou nada.** O padrão de falha é idêntico ao de
   15:46/15:58 — mesmo `full-speed`, mesmo `device descriptor read/64, error -71`,
   mesmo `unable to enumerate`. A hipótese "era só mau contato" está **morta**.

Nenhum `079b:0047`, nenhum `/dev/ttyACM*`. `probe.py` não foi rodado: sem
enumeração não existe device node pra abrir.

### O que NÃO fazer com esse resultado

A tabela de decisão da seção "PRÓXIMO PASSO EXATO" manda concluir "módulo não dá
boot" nesse cenário. **É prematuro.** As duas causas elétricas que ela mesma lista
como mais prováveis continuam abertas, e a principal nunca foi medida.

### PRÓXIMO PASSO, em ordem de custo/benefício

1. **Medir VBUS no módulo, plugado no USB, durante a tentativa de enumeração.**
   Furo nº 1 do handoff, pedido 5x e nunca respondido — agora é o único suspeito
   barato que sobrou. `DCV 20`, preto no fio preto, vermelho no fio vermelho.
   Esperado 4,5–5,2 V. Se cair pra ~4 V, a causa é queda no inrush pelos jumpers e
   o `-71` é consequência. **Sem esse número, "módulo morto" é palpite.**
2. **Plugar num hub USB 2.0** em vez da porta raiz xHCI. Grátis; já existem dois no
   barramento (`214b:7260` em `1-3`). Eletrônica de porta diferente, às vezes
   tolera integridade de sinal marginal que o xHCI rejeita.
3. **Encurtar e torcer o par verde/branco.** Não está claro que foi feito. Jumper de
   protoboard não tem os ~90 Ω diferenciais do par.

Se (1) medir certo, (2) falhar e (3) estiver feito → aí "o módulo não dá boot" passa
a ser a explicação de pé, e a decisão vira **insistir vs. comprar leitor
documentado** — lembrando que o bloqueio do `IDENTIFY` (`0x22`, dependente de
documento da Kronos/UKG) continua intacto nos dois casos.

---

## SESSÃO DE BANCADA 2026-08-05 — LEIA ISTO PRIMEIRO

**Resultado: dois transportes testados, ZERO bytes recebidos.** Nenhuma das duas
unidades respondeu a nada. Detalhe abaixo; a seção "PRÓXIMO PASSO EXATO" que vem
depois está **obsoleta** (mantida só pelo esquema de ligação, que segue válido).

### Existem DUAS unidades, e são modelos DIFERENTES

| | Módulo 1 | Módulo 2 |
|---|---|---|
| Modelo | **MSO CBM** | **CBM-E3 / MPH-SE001A** |
| P/N | 293652806 | **293658783** |
| Alimentação | 3–5,5 V / 500 mA | 3,6–5,5 V / 0,5 A |
| Origem | desconhecida | **Kronos InTouch 9000** (confirmado: o P/N é vendido como peça dele) |
| Conector | harness de 4 fios | **FFC branco ~10–12 vias**, sem harness |
| Extras | — | FBI PIV IQS + STQC; coder/matcher MINEX **embarcado** |

Não trate como "duas unidades iguais" — qualquer raciocínio do tipo "duas mortas é
improvável" **não se aplica**, e `morpho_ilv.py` (ILV do MorphoSmart) pode nem servir
pro E3.

**O dono dos documentos tem nome: Kronos / UKG.**

### O que foi provado com teste controlado

- **A porta USB do PC está inocente.** O CP2102 enumera sem um erro em `usb 1-2`,
  a mesma porta que dá `-71` com o módulo. Não é cabo, porta nem xHCI.
- **O rig de teste serial está validado.** Laço TXD↔RXD devolve o frame
  byte-perfeito nos 5 bauds (`53:59:4e:43` = `SYNC`). Isso também promoveu o
  enquadramento do `morpho_ilv.py` de "testado só contra PTY" pra **testado sobre
  UART real**.
- **Existe um pull-up de baixa impedância no fio amarelo** (segura >2 V contra os
  15 kΩ do host). Provado por manipulação: a velocidade anunciada acompanha a troca
  dos fios — amarelo→D+ dá `full-speed`, amarelo→D− dá `low-speed`.
- **USB nunca enumera.** `-71` / `device not accepting address`, 4 de 4, idêntico,
  **nas duas polaridades**. Erro que não muda com a inversão não é erro de pinagem.
- **Serial nunca responde.** Silêncio em 38400/9600/19200/57600/115200.

### CORREÇÃO de uma afirmação errada que estava neste arquivo

A seção abaixo dizia que `full-speed` **provava** ser USB e que o caminho TTL estava
descartado. **Está errado, e o furo é este:** um **TX de UART em repouso alto** com
pull-up também é nível alto de baixa impedância num fio só, dispara a detecção de
"dispositivo conectado" do host, e a velocidade anunciada acompanha a troca de fios
**exatamente igual** a um D+ verdadeiro. O experimento distingue "tem pull-up no
amarelo" de "não tem" — **não** distingue USB de UART. O caminho TTL do README
**não** está descartado.

### Ressalva que domina tudo

O pull-up é resistor passivo pro trilho 3,3 V: aparece com a energia **mesmo com o
firmware morto ou em reset**. Tudo que observamos hoje é explicável por *um regulador
ligado e um resistor*. **Não há evidência de processador rodando em nenhuma das
unidades.** Os 23 mA @ 4,99 V são coerentes com isso (não provam isolados).

### Evidência quantificada do barramento (17:06, mesmo dia)

Análise do `journalctl -k` cobrindo 15:46 → 17:06 na porta `usb 1-2`:

| Métrica | Valor |
|---|---|
| Tentativas de enumeração do módulo | **64** |
| Ciclos completos `unable to enumerate` | **14** |
| Enumerações bem-sucedidas do módulo | **0** |
| Enumerações bem-sucedidas do CP2102 na mesma porta | **8** (`10c4:ea60`) |
| `full-speed` / `low-speed` anunciados | 64 / 4 |

Conclusões que esses números fecham:

- **A porta está inocente com 8 provas**, intercaladas às falhas. Não é porta, cabo
  nem xHCI.
- **Os 4 `low-speed` são o experimento de inverter azul/amarelo** — falharam com o
  mesmo `-71`. **Erro que não muda ao inverter os dados não é erro de pinagem.**
- 68 tentativas, 2 mapeamentos, resultado idêntico: **parou de ser problema de
  fiação.** Replugar não gera informação nova.

### Furos que ainda podem virar o jogo (nenhum foi fechado)

1. **Nunca foi medido se chega 5 V no módulo durante os testes TTL.** Pedido 5x sem
   resposta. Se o pino usado no CP2102 entrega 3,3 V ou nada, **todo o silêncio TTL
   é falso negativo** e a análise acima desaba. `DCV 20`, preto no fio preto,
   vermelho no fio vermelho: tem que dar 4,5–5,2 V.
2. **O teste TTL com amarelo/azul invertidos nunca rodou** (a porta havia caído).
3. **O pull-up de 4k7** no TX (open-collector) — não testado, faltam resistores.
4. **O módulo 2 nunca foi ligado em nada** — não tem harness pro conector FFC.

### Armadilhas de método (custaram a sessão)

- **Nunca rode teste sem confirmar a montagem física.** Rodei `--scan-baud` três
  vezes sem saber se o módulo estava ligado/energizado; resultado ininterpretável.
- **Valide o instrumento antes de acreditar num negativo.** O laço TXD↔RXD é o
  controle positivo; sem ele, "silêncio" não é dado.
- **`journalctl -k` cobre o barramento inteiro** — ausência de `-71` em qualquer
  porta prova que o módulo não está ligado em porta nenhuma.

---

## PRÓXIMO PASSO EXATO (OBSOLETO — ver seção acima; só o esquema de ligação vale)

Ligar os fios de dados e ver se enumera como USB:

```
USB vermelho (VBUS) -> vermelho      USB branco (D-) -> azul
USB preto    (GND)  -> preto         USB verde  (D+) -> amarelo
```

Fonte única pelo USB — **não** alimentar pela bancada com o VBUS ligado junto
(dois 5 V brigando; e o módulo usa a presença do VBUS pra detectar o host).

Com `dmesg -w` aberto antes de plugar:

(`dmesg` está com `dmesg_restrict=1` nesta máquina; o usuário está no grupo `adm`,
então use **`journalctl -k -n 40 --no-pager`**.)

| Saída | Significado |
|---|---|
| `idVendor=079b, idProduct=0047` | Enumerou → rode `python3 probe.py` |
| `new **full-speed** device` + `error -71` | É USB e o mapeamento está **certo**. Falha elétrica — ver abaixo. **Não** troque azul/amarelo. |
| `new **low-speed** device` | Invertido → troca azul/amarelo (inofensivo) |
| Silêncio total | Não é USB nesses fios → caminho TTL (ver README) |

**A distinção full-speed/low-speed é o dado, não o `-71`.** Quem determina a
velocidade anunciada é o pull-up de 1,5 kΩ do dispositivo: em **D+** = full-speed,
em **D−** = low-speed (o host tem pull-down de 15 kΩ nas duas). Logo `full-speed`
já prova que a linha ligada ao D+ do host é o D+ do módulo — mapeamento correto —
e o `-71` (EPROTO) é da camada elétrica, não da pinagem.

Isso também exclui o caminho TTL: o UART do CBM é **open-collector** (README),
só puxa pra baixo. Sem o pull-up de 4k7 (que ficou na placa do relógio ponto) o TX
flutua e o pull-down de 15 kΩ do host o levaria pra **baixo** — um TX open-collector
solto não consegue fazer o host anunciar full-speed.

Causas do `-71` com mapeamento certo, em ordem: (1) integridade de sinal — jumper de
protoboard não tem os ~90 Ω diferenciais do par D+/D−; (2) queda de VBUS no inrush
(até ~300 mA reais) pelos mesmos jumpers finos. Encurtar e **torcer** o par D+/D−
antes de suspeitar de qualquer outra coisa.

### CONFIRMADO EXPERIMENTALMENTE (2026-08-05) — fase 1 fechada

Teste com as duas polaridades, mesma bancada, resultado reprodutível:

| Ligação | Host anuncia | Conclusão |
|---|---|---|
| amarelo → verde (D+) | `full-speed` (2x: 15:46, 15:58) | pull-up está no amarelo |
| amarelo → branco (D−) | `low-speed` (16:02) | pull-up está no amarelo |

**A velocidade acompanhou o fio** → o pull-up é real e de baixa impedância
(segurou >2 V contra os 15 kΩ do host nas duas orientações). Ligação a usar:
amarelo→verde, azul→branco.

> ⚠️ **O parágrafo original aqui afirmava que isso provava ser USB e que o caminho
> TTL estava descartado. ERRADO** — ver "CORREÇÃO" no topo do arquivo. O teste prova
> que existe pull-up no amarelo; **não** distingue D+ de USB de um TX de UART em
> repouso alto. A pergunta "USB ou TTL?" continua **aberta**.

Não perca tempo com multímetro nas linhas de dados: o D− é um pino genuinamente
flutuante no dispositivo (o pull-down de 15 kΩ é do *host*), então voltímetro de
10 MΩ lê lixo ali por definição — medimos 2,89 V no amarelo e 1,86 V no azul, e o
1,86 V não significava nada. O host, ao plugar, já aplica a carga de 15 kΩ que
torna o teste de bancada redundante.

**Ressalva:** o pull-up é um resistor passivo pro trilho 3,3 V — aparece com a
energia, **mesmo com o firmware morto**. O `full-speed` prova o fio, não que o
módulo inicializa. Se o `-71` sobreviver à correção elétrica, a hipótese principal
passa a ser "módulo não dá boot".

Inverter os fios de dados **não danifica nada**. Não há mais passo irreversível
no projeto.

## O bloqueio real da fase 3

O `IDENTIFY` (ILV `0x22`): o pyMorphoILV traz o **parser da resposta** mas não o
**montador da requisição**. O decoder já está pronto em `morpho_ilv.py`; falta
montar os parâmetros do comando. Fontes, em ordem de preferência:

1. Projeto **`MSO ILV_Sample`** (fonte em C, vem no SDK) — atalho real
2. **MorphoSmart Host System Interface Specification** (`.chm`)
3. **`SSE-0000077475`** — "MorphoSmart CBM Module Integration": pinagem dos 8 pinos
   + circuito adaptador
4. Empiricamente, com `probe.py --raw`, usando `INVALID_COMMAND` (`0x50`) como
   sinal de "chegou mas não entendi"

**Quem tem esses documentos é o fabricante do relógio ponto** — foi o que ele usou.
Vale pedir antes de partir pra engenharia reversa.

**Identificado em 2026-08-05: é a Kronos / UKG.** O P/N 293658783 do módulo 2 é
vendido no mercado de peças como "CBM-E3 **Kronos InTouch 9000** fingerprint module".
Peças correlatas do mesmo equipamento: `8609020-001` e `8609042-001` ("Touch ID
Plus", que é o rótulo branco na etiqueta do módulo 2). Canal de pedido: suporte
técnico da UKG, ou os revendedores de peças que anunciam esses P/N.

**Nota de escopo:** este bloqueio é independente do bloqueio elétrico. Mesmo que o
módulo acorde, sem o formato da requisição `0x22` não há identificação 1:N. São dois
bloqueios em série, e este depende de terceiro. Considerar isso na decisão de
insistir vs. comprar leitor documentado.

## Como o usuário trabalha

Escreve em português. Prefere que erros e limitações sejam ditos na cara, não
contornados. Corrigir suposição minha errada quando aparecer evidência nova é
esperado — já aconteceu duas vezes neste projeto (capacidade de templates, e eu
ter afirmado "é TTL" cedo demais sem prova).
