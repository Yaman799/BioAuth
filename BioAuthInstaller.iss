; Inno Setup script for BioAuth Desktop

#ifndef MyAppName
  #define MyAppName "BioAuth Desktop"
#endif

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

#ifndef MyAppVersionNumeric
  #define MyAppVersionNumeric "1.0.0.0"
#endif

#ifndef MyAppPublisher
  #define MyAppPublisher "BioAuth"
#endif

#ifndef MyAppURL
  #define MyAppURL "https://github.com/alakhrs543-maker/BioAuth"
#endif

#ifndef MyAppExeName
  #define MyAppExeName "BioAuth.exe"
#endif

[Setup]
AppId={{0FDEB57A-7D51-4F55-9AF8-5A8A53D8E622}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
VersionInfoVersion={#MyAppVersionNumeric}
VersionInfoProductVersion={#MyAppVersion}
DefaultDirName={localappdata}\Programs\BioAuth Desktop
DefaultGroupName=BioAuth Desktop
AllowNoIcons=yes
DisableProgramGroupPage=yes
LicenseFile=EULA.txt
OutputDir=installer
OutputBaseFilename=BioAuthDesktopSetup_{#MyAppVersion}
SetupIconFile=bioauth.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
CloseApplications=yes
RestartApplications=no
UsedUserAreasWarning=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startup"; Description: "Launch BioAuth automatically when you sign in to Windows"; GroupDescription: "Startup behavior:"; Flags: unchecked

[Files]
Source: "dist\BioAuth\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "EULA.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "PRIVACY_POLICY.md"; DestDir: "{app}"; Flags: ignoreversion

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "BioAuthDesktop"; \
    ValueData: """{app}\{#MyAppExeName}"" --background"; \
    Tasks: startup; Flags: uninsdeletevalue

[Icons]
Name: "{group}\BioAuth Desktop"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall BioAuth Desktop"; Filename: "{uninstallexe}"
Name: "{autodesktop}\BioAuth Desktop"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; \
    Flags: nowait postinstall skipifsilent

[Code]
function BioAuthDataDir(): string;
begin
  Result := ExpandConstant('{localappdata}\BioAuth');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpSelectTasks) and WizardIsTaskSelected('startup') then
  begin
    MsgBox(
      'BioAuth will start in the background when you sign in to Windows.'#13#10#13#10 +
      'Startup does not bypass sign-in, consent, model readiness, or protected-session safety checks.'#13#10 +
      'Protected sessions after startup require the separate in-app setting and valid remembered-login state.',
      mbInformation,
      MB_OK
    );
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Answer: Integer;
  DataDir: string;
begin
  if CurUninstallStep = usUninstall then
  begin
    DataDir := BioAuthDataDir();
    if DirExists(DataDir) then
    begin
      Answer := MsgBox(
        'Do you want to delete local BioAuth data too?'#13#10#13#10 +
        'Choose No to preserve accounts, settings, sessions, logs, trained models, evaluation evidence, and templates.'#13#10#13#10 +
        'Choose Yes only if you intentionally want to remove local BioAuth data stored in:'#13#10 +
        DataDir,
        mbConfirmation,
        MB_YESNO
      );
      if Answer = IDYES then
      begin
        DelTree(DataDir, True, True, True);
      end;
    end;
  end;
end;
