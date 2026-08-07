# Instalar o bio-pdv no Windows

Duas etapas separadas, e só a primeira exige Python:

1. **Gerar o instalador** — uma vez, numa máquina qualquer com Python.
2. **Instalar nos PCs** — duplo clique no `bio-pdv-setup.exe`. Sem Python, sem terminal.

---

## Etapa 1 — Gerar o instalador (uma vez só)

Numa máquina Windows com **Python 3.10+** ([python.org](https://python.org) — marque
**"Add Python to PATH"** na instalação):

```
build-windows.bat          (duplo clique)
```

Leva alguns minutos e produz `dist\bio-pdv\bio-pdv.exe`. Esse `.exe` já funciona
sozinho — se você só quer testar, pode parar aqui e copiar a pasta `dist\bio-pdv`
para o PC do caixa.

Para o instalador de verdade, instale o [Inno Setup](https://jrsoftware.org/isdl.php),
abra `instalador.iss` e clique em **Compile**. Sai:

```
Output\bio-pdv-setup.exe
```

Esse arquivo único é o que você leva para os PCs.

---

## Etapa 2 — Instalar nos PCs

Duplo clique em `bio-pdv-setup.exe`. Ele pergunta o tipo de instalação:

| Tipo | Onde usar | O que instala |
|---|---|---|
| **PC do caixa** | máquina do PDV | agente: bolha flutuante + atalho `Ctrl+Alt+B` |
| **PC do administrador** | seu note | só a tela de gestão de supervisores |
| **Completo** | máquina de teste | os dois |

No caixa, deixe marcado **"Iniciar o agente junto com o Windows"**.

> O instalador pede privilégio de administrador **de propósito**: se o PDV rodar
> elevado, o agente precisa estar no mesmo nível para conseguir digitar nele
> (restrição UIPI do Windows).

---

## Como acessar a interface

Depois de instalado, três caminhos — todos levam à mesma tela:

1. **Menu Iniciar → bio-pdv → Gerenciar supervisores**
2. **Atalho na área de trabalho** (se marcou na instalação)
3. **Ícone na bandeja** (perto do relógio): **um clique abre a gestão**;
   botão direito abre o menu

> No Windows o ícone da bandeja costuma ficar escondido atrás da setinha `^`.
> Arraste ele para fora uma vez e ele fica fixo.

Na **primeira execução**, se não houver nenhum supervisor cadastrado, a tela de
gestão abre sozinha — você não precisa procurar nada.

### No caixa, o dia a dia

O operador vê uma **bolha azul** flutuando (arrastável, fica onde você largar).
Quando o PDV pedir a senha de supervisor:

1. Operador clica na bolha (ou tecla `Ctrl+Alt+B`)
2. Supervisor encosta o dedo
3. A senha é digitada sozinha no campo

Bolha azul = pronta · amarela = lendo · verde = liberado · vermelha = negado.

---

## Antes de liberar em produção

**1. O Windows reconhece o leitor?** Plugue e abra o *Gerenciador de Dispositivos*.
Tem que aparecer uma **porta COM** (em "Portas (COM e LPT)").

Esse é o único risco que não dá para descartar antes de testar: o descritor USB
desse módulo é fora de norma e o Linux precisou de contorno. Se o Windows também
recusar, aparece como dispositivo desconhecido — me avise que existe saída
(instalar um `.inf` genérico apontando o `usbser.sys` para `VID_079B&PID_0047`).

**2. Cadastre os supervisores** pela tela de gestão, e configure **no PDV** a mesma
senha que o programa sorteou para cada login.

**3. Teste com o PDV real** antes de contar com isso num dia de movimento.

---

## Onde ficam os dados

```
%APPDATA%\bio-pdv\cofre.json        índice biométrico -> senha (cifrado com DPAPI)
%APPDATA%\bio-pdv\auditoria.jsonl   quem liberou o quê, quando
```

O **DPAPI** amarra a cifra à conta do Windows daquela máquina: copiar o
`cofre.json` para outro PC não serve de nada. A auditoria nunca grava senha.

⚠️ **Faça backup do `cofre.json`.** Perdeu o cofre, perdeu o vínculo digital→senha
e é preciso recadastrar todo mundo. A desinstalação **não** apaga esses arquivos,
justamente por isso.

## Problemas comuns

| Sintoma | Causa provável |
|---|---|
| "Leitor não encontrado" | Sem porta COM. Ver *Gerenciador de Dispositivos* |
| Bolha fica vermelha com "Bloq." | UIPI: rode o agente como administrador |
| Digital lida mas nada é digitado | O campo perdeu o foco. Clique no campo antes da bolha |
| "Sem senha" na bolha | Digital está no leitor mas não neste PC. Cadastre pela gestão |
| Bolha não aparece | Bandeja → "Mostrar/ocultar botão flutuante" |
