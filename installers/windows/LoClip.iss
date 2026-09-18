; LoClip — instalador de Windows (Inno Setup 6). Se compila en GitHub Actions (ver .github/workflows/build-windows.yml).
; Instala por usuario (no pide administrador) en %LOCALAPPDATA%\Programs\LoClip.

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#ifndef BuildDir
  #define BuildDir "..\..\build"
#endif

[Setup]
AppId={{7E1C2C1A-5B7B-4D6E-9C1B-0C11F0000001}
AppName=LoClip
AppVersion={#AppVersion}
AppVerName=LoClip {#AppVersion}
AppPublisher=LoClip
DefaultDirName={localappdata}\Programs\LoClip
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=LoClip-Setup-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile={#BuildDir}\panel\icons\icon.ico
UninstallDisplayIcon={app}\panel\icons\icon.ico
WizardStyle=modern
CloseApplications=no

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
es.Welcome=LoClip busca en tu footage con IA, 100%% local. El instalador copia el motor, el panel de Premiere y, al final, descarga los componentes de IA (puede tardar varios minutos).
en.Welcome=LoClip searches your footage with AI, 100%% locally. Setup copies the engine, the Premiere panel and, at the end, downloads the AI components (this can take several minutes).
es.Finishing=Descargando componentes de IA…
en.Finishing=Downloading AI components…
es.StartLoClip=Iniciar LoClip (versión web)
en.StartLoClip=Start LoClip (web version)

[Files]
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion createallsubdirs

[Icons]
Name: "{autoprograms}\{cm:StartLoClip}"; Filename: "{app}\Iniciar LoClip.cmd"; IconFilename: "{app}\panel\icons\icon.ico"
Name: "{autodesktop}\{cm:StartLoClip}"; Filename: "{app}\Iniciar LoClip.cmd"; IconFilename: "{app}\panel\icons\icon.ico"

[Registry]
Root: HKCU; Subkey: "Software\Adobe\CSXS.11"; ValueType: string; ValueName: "PlayerDebugMode"; ValueData: "1"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Adobe\CSXS.12"; ValueType: string; ValueName: "PlayerDebugMode"; ValueData: "1"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Adobe\CSXS.13"; ValueType: string; ValueName: "PlayerDebugMode"; ValueData: "1"; Flags: uninsdeletevalue

[Run]
Filename: "{app}\python\python.exe"; Parameters: """{app}\bootstrap.py"""; StatusMsg: "{cm:Finishing}"; Flags: waituntilterminated

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C curl -s -X POST http://127.0.0.1:47821/api/shutdown"; Flags: runhidden; RunOnceId: "stopengine"

[UninstallDelete]
Type: filesandordirs; Name: "{userappdata}\Adobe\CEP\extensions\com.loclip.panel"
Type: filesandordirs; Name: "{app}"

[Code]
procedure InitializeWizard;
begin
  WizardForm.WelcomeLabel2.Caption := ExpandConstant('{cm:Welcome}');
end;
