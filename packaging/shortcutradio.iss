; Inno Setup script for ShortCutRadio on Windows. Run through packaging\build.ps1,
; which passes the version and builds dist\ShortCutRadio\ first:
;
;     ISCC.exe /DAppVersion=0.1.0 packaging\shortcutradio.iss
;
; The Windows counterpart of the .deb: a Start menu entry, an uninstaller, and
; the settings in %APPDATA%\ShortCutRadio, which uninstalling leaves alone.
; Per user by default (no administrator prompt); the first page offers
; installing for everyone instead.

#ifndef AppVersion
  #error Pass /DAppVersion=<version> (packaging\build.ps1 does)
#endif
#define Root SourcePath + "\.."

[Setup]
AppId={{6C8CE50D-035B-4631-88E5-B0A190672ACE}
AppName=ShortCutRadio
AppVersion={#AppVersion}
AppPublisher=msvdm
AppPublisherURL=https://github.com/msvdm/ShortCutRadio
DefaultDirName={autopf}\ShortCutRadio
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#Root}\dist
OutputBaseFilename=ShortCutRadio-{#AppVersion}-windows-x64-setup
SetupIconFile={#Root}\build\shortcutradio.ico
UninstallDisplayIcon={app}\shortcutradio.exe
UninstallDisplayName=ShortCutRadio
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; Flags: unchecked

[InstallDelete]
; An upgrade replaces the libraries whole: a file the new build no longer has
; must not linger beside it.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#Root}\dist\ShortCutRadio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs
Source: "{#Root}\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Root}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Root}\packaging\THIRD_PARTY-windows.txt"; DestDir: "{app}"; DestName: "THIRD_PARTY.txt"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\ShortCutRadio"; Filename: "{app}\shortcutradio.exe"
Name: "{autodesktop}\ShortCutRadio"; Filename: "{app}\shortcutradio.exe"; Tasks: desktopicon

[UninstallRun]
; Close the running copy first, or every file it holds stays behind: unlike
; Setup, the uninstaller has no Restart Manager to do it.
Filename: "{app}\shortcutradio.exe"; Parameters: "--quit"; Flags: runhidden waituntilterminated; RunOnceId: "QuitApp"

[Run]
Filename: "{app}\shortcutradio.exe"; Description: "{cm:LaunchProgram,ShortCutRadio}"; Flags: nowait postinstall skipifsilent

[Code]
// A copy running as administrator (its "Run as administrator" switch) is out
// of the Restart Manager's reach when Setup is not: ask it to close the way
// uninstalling does, before files are replaced.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Exe: String;
  Code: Integer;
begin
  Exe := ExpandConstant('{app}\shortcutradio.exe');
  if FileExists(Exe) then
    Exec(Exe, '--quit', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := '';
end;
