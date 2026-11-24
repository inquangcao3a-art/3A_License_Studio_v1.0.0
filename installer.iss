#define AppName "AI Font Finder PRO"
#define AppVersion "7.1.1"
#define AppPublisher "THIET KE IN AN QUANG CAO 3A"
#define ShortcutIcon "AI_Font_Finder_PRO_7.1.1.ico"
#define AppExe "AI_Font_Finder_PRO.exe"
[Setup]
AppId={{A9B7D634-10AF-45A3-B880-F02AF2026A3A}
AppName={#AppName}
AppVersion={#AppVersion}
VersionInfoVersion=7.1.1.0
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\AI Font Finder PRO 3A
DefaultGroupName={#AppName}
OutputDir=output
OutputBaseFilename=AI_Font_Finder_PRO_7.1.1_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#ShortcutIcon}
PrivilegesRequired=admin
SetupIconFile=ai_pro_logo.ico
[InstallDelete]
; PyInstaller runtime files from earlier installs must not mix with this release.
Type: filesandordirs; Name: "{app}\_internal"
[Files]
Source: "ai_pro_logo.ico"; DestDir: "{app}"; DestName: "{#ShortcutIcon}"; Flags: ignoreversion
Source: "dist\AI_Font_Finder_PRO\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\{#ShortcutIcon}"; IconIndex: 0
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\{#ShortcutIcon}"; IconIndex: 0; Tasks: desktopicon
[Tasks]
Name: desktopicon; Description: "Tao bieu tuong Desktop"; GroupDescription: "Tuy chon:"
[Run]
Filename: "{app}\{#AppExe}"; Description: "Mo {#AppName}"; Flags: nowait postinstall skipifsilent
