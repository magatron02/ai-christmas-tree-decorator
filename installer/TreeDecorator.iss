; Installer for the desktop build of Tree Decorator.
;
; Per-user by design: PrivilegesRequired=lowest puts the app under %LOCALAPPDATA%, which the
; running app can write to. That matters because this program keeps live data beside its own
; exe — the catalogue the settings page edits, the SQLite spend log, generated pictures and
; the API key — and a Program Files install would have made every one of those read-only.

#define AppName "Tree Decorator"
#define AppVersion "1.0.3"
#define AppPublisher "VR Twin"
#define AppExe "TreeDecorator.exe"

[Setup]
AppId={{8E2C4B71-5A63-4F0E-9D2A-7C1B6E4A9F30}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist_installer
OutputBaseFilename=TreeDecorator-Setup-{#AppVersion}
SetupIconFile=..\frontend\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; the frozen Python app (exe + _internal/)
; Excludes matter: scripts/stage_desktop_build.py copies frontend/, catalog/ and models/ into
; this same folder so the frozen exe can be tested before packaging. Without them a test run
; would smuggle a second copy of the catalogue in through this glob — installed with
; ignoreversion, which is exactly the overwrite the onlyifdoesntexist rule below exists to
; prevent. Runtime leftovers (.env, data\, storage\, logs) are excluded for the same reason:
; they are the developer's, not the shop's.
Source: "..\dist\TreeDecorator\*"; DestDir: "{app}"; Excludes: "frontend\*,catalog\*,models\*,data\*,storage\*,*.log,.env"; Flags: ignoreversion recursesubdirs createallsubdirs

; served web assets — ROOT-relative at runtime, so they sit beside the exe not inside _internal
Source: "..\frontend\*"; DestDir: "{app}\frontend"; Flags: ignoreversion recursesubdirs createallsubdirs

; the catalogue. onlyifdoesntexist on the JSON so a reinstall never overwrites products the
; shop added from the settings page; the photos are content and are refreshed normally.
Source: "..\catalog\*.json"; DestDir: "{app}\catalog"; Flags: onlyifdoesntexist
Source: "..\catalog\embeddings.npy"; DestDir: "{app}\catalog"; Flags: onlyifdoesntexist
Source: "..\catalog\images\*"; DestDir: "{app}\catalog\images"; Flags: ignoreversion recursesubdirs createallsubdirs

; Cut-outs made ahead of time by scripts/precut_catalog.py, so picking a decoration is a file
; read instead of a run of rembg. skipifsourcedoesntexist because they are an optimisation:
; a build without them still produces a working installer, just one that cuts on the fly.
Source: "..\catalog\cutouts\*"; DestDir: "{app}\catalog\cutouts"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

; rembg's cut-out model, so the first background removal works offline instead of pulling
; 168 MB down mid-click. scripts/launcher.py points U2NET_HOME here.
Source: "..\build_assets\models\u2net.onnx"; DestDir: "{app}\models"; Flags: ignoreversion

[Dirs]
; written at runtime; created up front so a first run never has to
Name: "{app}\data"
Name: "{app}\storage"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; only what the app generated. The catalogue, the spend log and the API key are the user's
; own data and are deliberately left behind for a reinstall to pick up.
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\models"
Type: filesandordirs; Name: "{app}\frontend"
