; Installer Windows di 3DGen (Inno Setup 6).
;
; Si compila con:  iscc packaging\3dgen.iss
; Prima serve la cartella dist\3DGen, prodotta da:  python packaging\build.py
;
; Nota: questo script non e' mai stato compilato su questa macchina, perche'
; Inno Setup non e' installato. E' scritto secondo la documentazione di
; Inno Setup 6 e va provato prima di distribuirlo.

#define AppName "3DGen"
#define AppVersion "0.1.0"
#define AppPublisher "3DGen"
#define AppExe "3DGen.exe"

[Setup]
AppId={{7C1B4E4A-9E0B-4A4E-9C4E-3DGEN0000001}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputDir=..\dist
OutputBaseFilename={#AppName}-setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
; L'utente comune non deve avere bisogno dell'amministratore per installare
; nella propria cartella: si chiede il privilegio solo se lo sceglie.
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#AppExe}

[Languages]
Name: "italiano"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\3DGen\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; La cartella dei recuperi e i log sono creati a runtime dentro l'installazione:
; senza questo resterebbero indietro dopo la disinstallazione. La libreria e i
; progetti dell'utente **non** vengono toccati: sono suoi.
Type: filesandordirs; Name: "{app}\output\.recupero"
Type: filesandordirs; Name: "{app}\logs"
