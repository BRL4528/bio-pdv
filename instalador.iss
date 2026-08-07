; Instalador do bio-pdv (Inno Setup 6+) — https://jrsoftware.org/isdl.php
;
; Antes: rode build-windows.bat para gerar dist\bio-pdv\
; Depois: abra este arquivo no Inno Setup e clique Compile.
; Sai: Output\bio-pdv-setup.exe  (instalador unico, para dar duplo clique)

#define Nome     "bio-pdv"
#define Versao   "1.0.0"
#define Autor    "COOASGO"
#define Exe      "bio-pdv.exe"

[Setup]
AppId={{7A4C1E2B-9D3F-4A85-B1C6-2E8F0D5A7B31}
AppName={#Nome}
AppVersion={#Versao}
AppPublisher={#Autor}
DefaultDirName={autopf}\{#Nome}
DefaultGroupName={#Nome}
OutputBaseFilename=bio-pdv-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Precisa de admin: o agente digita em programas que podem rodar elevados (UIPI)
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#Exe}

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Types]
Name: "caixa";      Description: "PC do caixa (agente que libera a senha)"
Name: "admin";      Description: "PC do administrador (so gestao de supervisores)"
Name: "completo";   Description: "Completo (agente + gestao)"

[Components]
Name: "agente"; Description: "Agente do PDV (bolha flutuante + atalho)"; Types: caixa completo
Name: "gestao"; Description: "Gestao de supervisores";                   Types: admin completo

[Files]
Source: "dist\bio-pdv\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Gerenciar supervisores"; Filename: "{app}\{#Exe}"; Parameters: "--gestao"; Components: gestao
Name: "{group}\Agente do PDV";          Filename: "{app}\{#Exe}"; Parameters: "--agente"; Components: agente
Name: "{group}\Desinstalar {#Nome}";    Filename: "{uninstallexe}"
Name: "{autodesktop}\Gerenciar supervisores"; Filename: "{app}\{#Exe}"; Parameters: "--gestao"; Tasks: atalhodesktop; Components: gestao

[Tasks]
Name: "atalhodesktop"; Description: "Criar atalho na area de trabalho"; GroupDescription: "Atalhos:"; Components: gestao
Name: "autostart";     Description: "Iniciar o agente junto com o Windows (recomendado no caixa)"; GroupDescription: "Inicializacao:"; Components: agente

[Registry]
; Auto-start do agente. Roda elevado porque o instalador exige admin.
Root: HKLM; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "bio-pdv"; \
  ValueData: """{app}\{#Exe}"" --agente"; \
  Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#Exe}"; Parameters: "--gestao"; Description: "Abrir a gestao de supervisores agora"; \
  Flags: nowait postinstall skipifsilent; Components: gestao
Filename: "{app}\{#Exe}"; Parameters: "--agente"; Description: "Iniciar o agente agora"; \
  Flags: nowait postinstall skipifsilent; Components: agente and not gestao

[UninstallDelete]
; O cofre e a auditoria ficam em %APPDATA%\bio-pdv e NAO sao apagados de
; proposito: perder o cofre significa perder o vinculo digital->senha, e a
; auditoria pode ser necessaria depois da desinstalacao.
