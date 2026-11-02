; Inno Setup prototype for a PyInstaller onedir bundle. Unsigned by default.
; Build Windows bundle using build_windows.ps1 before compiling.
#define AppName "Garfield"
#define AppVersion "0.5.0-preview"
#define AppExe "Garfield.exe"

[Setup]
AppId={{817AA476-0693-4DC8-AABB-854BE6A769B7}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Garfield project
DefaultDirName={localappdata}\Programs\Garfield
DefaultGroupName=Garfield
OutputDir=..\dist\installers
OutputBaseFilename=Garfield-Setup-preview
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\Garfield.exe
WizardStyle=modern

[Files]
Source: "..\dist\Garfield\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Garfield"; Filename: "{app}\Garfield.exe"
Name: "{userdesktop}\Garfield"; Filename: "{app}\Garfield.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Ярлыки:"; Flags: unchecked

[Run]
Filename: "{app}\Garfield.exe"; Description: "Запустить Garfield"; Flags: nowait postinstall skipifsilent
