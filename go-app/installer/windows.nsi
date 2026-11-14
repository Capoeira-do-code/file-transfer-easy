; NSIS installer for File Transfer Easy.
;
; Built by scripts/build-windows.ps1 after the .exe exists:
;   makensis /DVERSION=1.0.0 installer\windows.nsi
;
; Installs per user, so no administrator prompt is needed, and registers an
; uninstaller plus Start Menu and desktop shortcuts.

Unicode true

!ifndef VERSION
  !define VERSION "1.1.0"
!endif
!ifndef SOURCE_EXE
  !define SOURCE_EXE "..\dist\FileTransferEasy-${VERSION}-windows-amd64.exe"
!endif

!define APP_NAME    "File Transfer Easy"
!define APP_EXE     "FileTransferEasy.exe"
!define PUBLISHER   "File Transfer Easy"
!define UNINST_KEY  "Software\Microsoft\Windows\CurrentVersion\Uninstall\FileTransferEasy"

!include "MUI2.nsh"

Name "${APP_NAME}"
OutFile "..\dist\FileTransferEasy-Setup-${VERSION}.exe"
InstallDir "$LOCALAPPDATA\Programs\FileTransferEasy"
InstallDirRegKey HKCU "Software\FileTransferEasy" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma

VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName"     "${APP_NAME}"
VIAddVersionKey "FileDescription" "${APP_NAME}"
VIAddVersionKey "FileVersion"     "${VERSION}"
VIAddVersionKey "ProductVersion"  "${VERSION}"
VIAddVersionKey "CompanyName"     "${PUBLISHER}"

!define MUI_ICON "..\build\icons\icon.ico"
!define MUI_UNICON "..\build\icons\icon.ico"
!define MUI_ABORTWARNING

!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "Abrir ${APP_NAME}"

!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "Spanish"
!insertmacro MUI_LANGUAGE "English"

Section "Install"
  SetOutPath "$INSTDIR"

  ; A running copy would lock the executable.
  nsExec::Exec 'taskkill /F /IM "${APP_EXE}"'
  Pop $0

  File /oname=${APP_EXE} "${SOURCE_EXE}"

  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"
  CreateShortcut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"

  WriteRegStr HKCU "Software\FileTransferEasy" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName"     "${APP_NAME}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion"  "${VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher"       "${PUBLISHER}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon"     "$INSTDIR\${APP_EXE}"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" "$INSTDIR\Uninstall.exe"
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1

  WriteUninstaller "$INSTDIR\Uninstall.exe"
SectionEnd

Section "Uninstall"
  nsExec::Exec 'taskkill /F /IM "${APP_EXE}"'
  Pop $0

  Delete "$INSTDIR\${APP_EXE}"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"

  Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
  RMDir "$SMPROGRAMS\${APP_NAME}"
  Delete "$DESKTOP\${APP_NAME}.lnk"

  DeleteRegKey HKCU "${UNINST_KEY}"
  DeleteRegKey HKCU "Software\FileTransferEasy"

  ; The cached cloudflared and any settings live here.
  RMDir /r "$APPDATA\FileTransferEasy"
SectionEnd
