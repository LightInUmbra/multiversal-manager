; Inno Setup script for the installed version of Multiversal Manager. build.py compiles
; it after PyInstaller, passing AppVersion, SourceDir (the built app folder) and OutputDir.
;
; Installs for the current Windows user only, so no admin rights are needed. The collection
; lives in %LOCALAPPDATA%\Multiversal Manager (see database.py), which uninstalling leaves
; alone: removing the app never deletes anyone's collection.

#define AppName "Multiversal Manager"

[Setup]
; Keep this id the same forever: it's how a newer version upgrades this one in place
AppId={{F1EF9C2B-F7B3-41D3-962A-BFDBA08E25EC}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Umbra Ortiz
AppPublisherURL=https://github.com/LightInUmbra/multiversal-manager
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename={#OutputName}
UninstallDisplayIcon={app}\{#AppName}.exe
SetupIconFile=assets\icon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppName}.exe"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppName}.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppName}.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
