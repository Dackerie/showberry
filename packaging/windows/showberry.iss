; Inno Setup 6 Script for Showberry
; Requires Inno Setup 6.0 or higher

#define MyAppName "Showberry"
#define MyAppVersion "0.3.1"
#define MyAppPublisher "Dackerie"
#define MyAppURL "https://github.com/Dackerie/showberry"
#define MyAppExeName "showberry.exe"

[Setup]
AppId={{C89DA621-8F32-4775-BF61-A1E4FF0B94A9}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=..\..\LICENSE
OutputDir=..\..\output
OutputBaseFilename=Showberry-Windows-Setup-x86_64
SetupIconFile=icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
WizardStyle=modern
DisableDirPage=auto
DisableProgramGroupPage=auto

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\..\dist\showberry\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icon.ico"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; IconFilename: "{app}\icon.ico"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\showberry"
Type: filesandordirs; Name: "{localappdata}\Showberry"

[Registry]
Root: HKCR; Subkey: "magnet"; ValueType: string; ValueData: "URL:Magnet Protocol"; Flags: uninsdeletekey
Root: HKCR; Subkey: "magnet"; ValueName: "URL Protocol"; ValueType: string; ValueData: ""; Flags: uninsdeletevalue
Root: HKCR; Subkey: "magnet\shell\open\command"; ValueType: string; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Flags: uninsdeletevalue

Root: HKCR; Subkey: ".torrent"; ValueType: string; ValueData: "Showberry.Torrent"; Flags: uninsdeletekey
Root: HKCR; Subkey: "Showberry.Torrent"; ValueType: string; ValueData: "BitTorrent Seed File"; Flags: uninsdeletekey
Root: HKCR; Subkey: "Showberry.Torrent\DefaultIcon"; ValueType: string; ValueData: "{app}\icon.ico,0"; Flags: uninsdeletevalue
Root: HKCR; Subkey: "Showberry.Torrent\shell\open\command"; ValueType: string; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Flags: uninsdeletevalue
