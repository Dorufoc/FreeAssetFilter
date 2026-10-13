Unicode true
; Prioritize smallest installer size over build/extraction speed.
; Keep bootstrap files independently extractable so the GUI appears immediately.
SetCompressor lzma
SetCompressorDictSize 64
!include LogicLib.nsh
RequestExecutionLevel admin
ManifestDPIAware true
Name "FreeAssetFilter Installer"
OutFile "..\build\FreeAssetFilter_NSIS_Setup.exe"
InstallDir "$PROGRAMFILES64\FreeAssetFilter"
InstallDirRegKey HKCU "Software\FreeAssetFilter" "InstallDir"
SilentInstall silent
SilentUninstall silent
ShowInstDetails nevershow

!define APP "FreeAssetFilter"
!define PAYLOAD "..\build\pyinstall\FreeAssetFilter"

Function .onInit
  InitPluginsDir
  SetOutPath "$PLUGINSDIR"
  File "..\build\installer\FreeAssetFilterInstaller.exe"
  File "..\build\installer\libwinpthread-1.dll"
  ; Show the lightweight GUI before unpacking the large PyInstaller payload.
  Exec '"$PLUGINSDIR\FreeAssetFilterInstaller.exe" /payload "$PLUGINSDIR\payload" /result "$PLUGINSDIR\install-result.txt"'
  SetOutPath "$PLUGINSDIR\payload"
  File /r "${PAYLOAD}\*"
  ; The GUI writes the result after the user completes or cancels.
  loop:
    IfFileExists "$PLUGINSDIR\install-result.txt" done
    Sleep 100
    Goto loop
  done:
  ClearErrors
  FileOpen $1 "$PLUGINSDIR\install-result.txt" r
  ${IfNot} ${Errors}
    FileRead $1 $INSTDIR
    FileClose $1
    StrCpy $INSTDIR $INSTDIR -2
    StrCmp $INSTDIR "CANCEL" cancel
  ${EndIf}
  Return
  cancel:
    Abort
FunctionEnd

Section "Install"
  WriteRegStr HKCU "Software\FreeAssetFilter" "InstallDir" "$INSTDIR"
  CreateDirectory "$SMPROGRAMS\FreeAssetFilter"
  CreateShortcut "$SMPROGRAMS\FreeAssetFilter\FreeAssetFilter.lnk" "$INSTDIR\FreeAssetFilter.exe"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilter" "DisplayName" "FreeAssetFilter"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilter" "UninstallString" '"$INSTDIR\Uninstall.exe"'
SectionEnd

Section "Uninstall"
  Delete "$INSTDIR\FreeAssetFilter.exe"
  RMDir /r "$INSTDIR\_internal"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  RMDir /r "$SMPROGRAMS\FreeAssetFilter"
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilter"
  DeleteRegKey HKCU "Software\FreeAssetFilter"
SectionEnd
