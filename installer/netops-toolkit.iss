#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#ifndef SourceDir
  #error SourceDir is not defined
#endif

#ifndef OutputDir
  #error OutputDir is not defined
#endif

[Setup]
AppId={{E5B8B0F9-5B63-4A5F-BB0A-89F14E37E7B8}
AppName=NetOps Toolkit
AppVersion={#AppVersion}
AppPublisher=NetOps Toolkit
DefaultDirName={autopf}\NetOps Toolkit
DefaultGroupName=NetOps Toolkit
DisableProgramGroupPage=yes
PrivilegesRequired=admin
OutputDir={#OutputDir}
OutputBaseFilename=NetOpsToolkit-setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\assets\icons\netops_toolkit.ico
UninstallDisplayIcon={app}\NetOpsToolkit.exe

[Tasks]
Name: "desktopicon"; Description: "바탕 화면 바로가기 만들기"; GroupDescription: "추가 아이콘:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\NetOps Toolkit"; Filename: "{app}\NetOpsToolkit.exe"
Name: "{autodesktop}\NetOps Toolkit"; Filename: "{app}\NetOpsToolkit.exe"; Tasks: desktopicon
