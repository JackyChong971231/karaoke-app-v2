; Inno Setup script for the Karaoke installer. Built by packaging/build.ps1, which stages the files in out\stage
; and passes /DAppVersion=<version from server/pyproject.toml>.

#ifndef AppVersion
  #error Pass /DAppVersion=x.y.z
#endif

[Setup]
AppId={{6B1E3F2A-9C4D-4E7B-8A51-2F0C9D7E4B13}
AppName=Karaoke
AppVersion={#AppVersion}
AppPublisher=Karaoke
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Karaoke
DisableDirPage=yes
DisableProgramGroupPage=yes
DefaultGroupName=Karaoke
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=out
OutputBaseFilename=Karaoke-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
UninstallDisplayName=Karaoke

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[InstallDelete]
; An upgrade replaces the app's code wholesale, so a file removed from a release never lingers.
Type: filesandordirs; Name: "{app}\server"
Type: filesandordirs; Name: "{app}\web"

[Files]
Source: "out\stage\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Karaoke"; Filename: "{app}\Karaoke.cmd"; WorkingDir: "{app}"; IconFilename: "{sys}\shell32.dll"; IconIndex: 168
Name: "{autodesktop}\Karaoke"; Filename: "{app}\Karaoke.cmd"; WorkingDir: "{app}"; IconFilename: "{sys}\shell32.dll"; IconIndex: 168; Tasks: desktopicon

[Run]
Filename: "{app}\Karaoke.cmd"; Description: "Start Karaoke now"; Flags: postinstall nowait skipifsilent shellexec

[UninstallDelete]
; The Python environment (1-3 GB) goes; songs, settings, and favourites in %LOCALAPPDATA%\Karaoke stay.
Type: filesandordirs; Name: "{localappdata}\Karaoke\runtime"
Type: filesandordirs; Name: "{localappdata}\Karaoke\updates"
