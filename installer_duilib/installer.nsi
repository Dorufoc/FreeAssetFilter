Unicode true
; Prioritize smallest installer size over build/extraction speed.
; Keep bootstrap files independently extractable so the GUI appears immediately.
SetCompressor lzma
SetCompressorDictSize 64
!include LogicLib.nsh
!include FileFunc.nsh
; Test-build isolation scaffolding. The test-mode macro checked here is a makensis
; command-line define; the production build never passes it and therefore always
; takes the `!else` branch below (unchanged behavior).
!ifdef FAF_TESTMODE
RequestExecutionLevel user
!else
RequestExecutionLevel admin
!endif
ManifestDPIAware true
Name "FreeAssetFilter Installer"
; Output override for isolated QA builds: pass -DFAF_OUTFILE=<path> on the
; makensis command line; the default below is the unchanged production artifact.
!ifndef FAF_OUTFILE
  !define FAF_OUTFILE "..\build\FreeAssetFilter_NSIS_Setup.exe"
!endif
OutFile "${FAF_OUTFILE}"
; Test build installs into the per-user profile (no elevation needed); the
; production build keeps the machine-wide Program Files default (unchanged).
!ifdef FAF_TESTMODE
InstallDir "$LOCALAPPDATA\FreeAssetFilterTest"
!else
InstallDir "$PROGRAMFILES64\FreeAssetFilter"
!endif
InstallDirRegKey HKCU "Software\FreeAssetFilter" "InstallDir"
SilentInstall silent
SilentUninstall silent
ShowInstDetails nevershow
; Setup / uninstaller icon: project icon (FAF-setup.ico) instead of the default NSIS icon.
Icon "..\freeassetfilter\icons\FAF-setup.ico"
UninstallIcon "..\freeassetfilter\icons\FAF-setup.ico"
; Numeric version 1.0.0.5; string versions come from FAFVERSION (1.0.0-alpha.5).
VIProductVersion "1.0.0.5"
VIAddVersionKey /LANG=1033 "ProductName" "FreeAssetFilter"
VIAddVersionKey /LANG=1033 "FileDescription" "FreeAssetFilter Installer"
VIAddVersionKey /LANG=1033 "FileVersion" "1.0.0-alpha.5"
VIAddVersionKey /LANG=1033 "ProductVersion" "1.0.0-alpha.5"
VIAddVersionKey /LANG=1033 "CompanyName" "Dorufoc & renmoren"
VIAddVersionKey /LANG=1033 "LegalCopyright" "Copyright (c) 2026 Dorufoc & renmoren"

!define APP "FreeAssetFilter"
!define PAYLOAD "..\build\pyinstall\FreeAssetFilter"
; Result protocol: the GUI install engine is the ONLY writer of this INI; NSIS is a
; pure reader. Only the terminal `abort` key (written last by the GUI) means
; "finished" - file existence alone is never used as the readiness signal.
!define RESULT_INI "$PLUGINSDIR\install-result.ini"
; Bounded wait for the terminal key. Production default 30 min, strictly greater
; than the GUI's own payload-wait default of 25 min (so the GUI never keeps waiting
; on a dead NSIS process). QA override: makensis -DFAF_WAIT_TIMEOUT_MS=60000 installer.nsi
!ifndef FAF_WAIT_TIMEOUT_MS
  !define FAF_WAIT_TIMEOUT_MS 1800000
!endif

; Automated test drive profile (contract §17): four 0/1 chars =
; desktop/startmenu/autostart/launch, forwarded to the test GUI as
; `/auto:opts=<bits>` (see the test Exec in .onInit). QA overrides it on the
; makensis command line (-DFAF_AUTO_PROFILE=1101); the !ifndef fallback keeps a
; plain `makensis -DFAF_TESTMODE installer.nsi` build compiling and runnable.
!ifdef FAF_TESTMODE
  !ifndef FAF_AUTO_PROFILE
    !define FAF_AUTO_PROFILE "1101"
  !endif
!endif

; First-seen latch for the GUI window liveness check: a missing window may only be
; treated as "died" after it has been observed at least once.
Var /GLOBAL Seen

Function .onInit
  InitPluginsDir
  SetOutPath "$PLUGINSDIR"
  ; GUI binary. Test branch embeds the FAF_TESTMODE build from
  ; tools/build_test_gui.ps1 (repo-root build/test-installer, a separate output
  ; dir from the production build/installer artifact). Production branch
  ; unchanged.
!ifdef FAF_TESTMODE
  File "..\build\test-installer\FreeAssetFilterInstaller.exe"
!else
  File "..\build\installer\FreeAssetFilterInstaller.exe"
!endif
  File "..\build\installer\libwinpthread-1.dll"
  ; Show the lightweight GUI before unpacking the large PyInstaller payload.
  ; Keep plain Exec (fire-and-forget): blocking on the launched process would
  ; stall the payload release below while the GUI itself waits for it -> deadlock.
  ; /result carries the INI path; /installdir pre-fills the Location page.
  ; Test branch drives the GUI unattended: /auto:opts=<bits> (contract §17)
  ; automates 欢迎→…→完成 with the frozen option bits (default 1101);
  ; production branch stays interactive (no /auto flag).
!ifdef FAF_TESTMODE
  Exec '"$PLUGINSDIR\FreeAssetFilterInstaller.exe" /payload "$PLUGINSDIR\payload" /result "${RESULT_INI}" /installdir "$INSTDIR" /auto:opts=${FAF_AUTO_PROFILE}'
!else
  Exec '"$PLUGINSDIR\FreeAssetFilterInstaller.exe" /payload "$PLUGINSDIR\payload" /result "${RESULT_INI}" /installdir "$INSTDIR"'
!endif
  SetOutPath "$PLUGINSDIR\payload"
  File /r "${PAYLOAD}\*"
  ; Payload-ready sentinel: written AFTER the payload release above completes and
  ; OUTSIDE the payload directory. The GUI waits for this before pre-scanning and
  ; copying. WriteINIStr takes 4 parameters: file / section / key / value.
  WriteINIStr "$PLUGINSDIR\payload.ready" "ready" "ready" "1"
  ; Readiness wait. An existing result file is NOT enough: the GUI creates the file
  ; first and fills it afterwards, so a non-empty terminal `abort` key is required.
  StrCpy $Seen 0
  StrCpy $2 0        ; elapsed ms
  StrCpy $3 0        ; consecutive ticks with the window gone after first sight
  loop:
    IfFileExists "${RESULT_INI}" 0 liveness
    ReadINIStr $0 "${RESULT_INI}" "install" "abort"
    StrCmp $0 "" 0 done
  liveness:
    FindWindow $R0 "FreeAssetFilterInstaller" ""
    StrCmp $R0 0 0 windowAlive
    ; Window not found: only judgeable once it has been seen at least once.
    StrCmp $Seen 1 0 tick
    IntOp $3 $3 + 1
    IntCmp $3 30 crash 0 crash
    Goto tick
  windowAlive:
    StrCpy $Seen 1
    StrCpy $3 0
  tick:
    Sleep 100
    IntOp $2 $2 + 100
    IntCmp $2 ${FAF_WAIT_TIMEOUT_MS} 0 0 timeout
    Goto loop
  timeout:
    ; Bounded fallback: no terminal key within FAF_WAIT_TIMEOUT_MS -> silent abort.
    Abort
  crash:
    ; The GUI window vanished after being seen without a terminal key -> GUI died
    ; (short grace above covers final INI flushes). Silent, bounded abort.
    Abort
  done:
  ; `dir` write-back strictly AFTER the terminal key is confirmed (before it,
  ; $INSTDIR would still hold the default / /installdir prefill value).
  ReadINIStr $0 "${RESULT_INI}" "install" "dir"
  StrCmp $0 "" dirDone
  StrCpy $INSTDIR $0
  dirDone:
  ReadINIStr $0 "${RESULT_INI}" "install" "abort"
  StrCmp $0 "1" 0 proceed
  Abort
  proceed:
  Return
FunctionEnd

Section "Install"
  ; Upgrade orphan cleanup: an older installer may have left the Uninstall entry in
  ; the 32-bit view (Wow6432Node); remove that same-named entry first so an upgrade
  ; cannot produce a duplicate Add/Remove Programs item. Production writes below go
  ; to the native 64-bit view.
  SetRegView 32
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilter"
  SetRegView 64
  WriteRegStr HKCU "Software\FreeAssetFilter" "InstallDir" "$INSTDIR"
  ; Optional desktop shortcut (flag from the result INI).
  ReadINIStr $0 "${RESULT_INI}" "install" "desktop"
  StrCmp $0 "1" 0 desktopDone
  CreateShortcut "$DESKTOP\FreeAssetFilter.lnk" "$INSTDIR\FreeAssetFilter.exe"
  desktopDone:
  ; Optional Start Menu shortcut (flag from the result INI).
  ReadINIStr $0 "${RESULT_INI}" "install" "startmenu"
  StrCmp $0 "1" 0 startmenuDone
  CreateDirectory "$SMPROGRAMS\FreeAssetFilter"
  CreateShortcut "$SMPROGRAMS\FreeAssetFilter\FreeAssetFilter.lnk" "$INSTDIR\FreeAssetFilter.exe"
  startmenuDone:
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  ; Add/Remove Programs metadata. Production (default branch below): native
  ; 64-bit HKLM view, unchanged. Test build: same value names written to the
  ; per-user HKCU hive under a distinct key (writable without elevation and
  ; never mixed with a production Add/Remove Programs entry).
!ifdef FAF_TESTMODE
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilterTest" "DisplayName" "FreeAssetFilter"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilterTest" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilterTest" "DisplayIcon" '"$INSTDIR\FreeAssetFilter.exe"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilterTest" "DisplayVersion" "1.0.0-alpha.5"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilterTest" "Publisher" "Dorufoc & renmoren"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilterTest" "URLInfoAbout" "https://github.com/Dorufoc/FreeAssetFilter"
  ; EstimatedSize is a DWORD in KB (${GetSize} with /S=0K returns the total in KB in $0).
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilterTest" "EstimatedSize" $0
!else
  ; Add/Remove Programs metadata (production: native 64-bit HKLM view).
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilter" "DisplayName" "FreeAssetFilter"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilter" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilter" "DisplayIcon" '"$INSTDIR\FreeAssetFilter.exe"'
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilter" "DisplayVersion" "1.0.0-alpha.5"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilter" "Publisher" "Dorufoc & renmoren"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilter" "URLInfoAbout" "https://github.com/Dorufoc/FreeAssetFilter"
  ; EstimatedSize is a DWORD in KB (${GetSize} with /S=0K returns the total in KB in $0).
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilter" "EstimatedSize" $0
!endif
  ; Optional autostart Run value. When disabled, delete only a value that is OURS
  ; (quote-consistent compare) - a value pointing elsewhere is never touched.
  ReadINIStr $0 "${RESULT_INI}" "install" "autostart"
  StrCmp $0 "1" 0 autostartOff
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "FreeAssetFilter" '"$INSTDIR\FreeAssetFilter.exe"'
  Goto autostartDone
  autostartOff:
  ReadRegStr $1 HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "FreeAssetFilter"
  StrCmp $1 '"$INSTDIR\FreeAssetFilter.exe"' 0 autostartDone
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "FreeAssetFilter"
  autostartDone:
SectionEnd

Section "Uninstall"
  ; Native 64-bit view first (production entries live there)...
  SetRegView 64
  ; Remove the Run value only if it still points at OUR executable (the compare
  ; string carries the same embedded quotes as the write); a foreign value is kept.
  ReadRegStr $1 HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "FreeAssetFilter"
  StrCmp $1 '"$INSTDIR\FreeAssetFilter.exe"' 0 runKeep
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "FreeAssetFilter"
  runKeep:
  Delete "$INSTDIR\FreeAssetFilter.exe"
  RMDir /r "$INSTDIR\_internal"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  Delete "$DESKTOP\FreeAssetFilter.lnk"
  RMDir /r "$SMPROGRAMS\FreeAssetFilter"
  ; Uninstall entry. Production removes the native 64-bit HKLM key here and the
  ; legacy 32-bit view key further below; the test build removes its per-user
  ; HKCU key instead at both sites (HKCU\...\Uninstall is not WOW64-redirected,
  ; so the deletion is idempotent).
!ifdef FAF_TESTMODE
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilterTest"
!else
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilter"
!endif
  DeleteRegKey HKCU "Software\FreeAssetFilter"
  ; ...then repeat the same-named Uninstall key deletion in the 32-bit view to also
  ; clean up entries left there by legacy installers.
  SetRegView 32
!ifdef FAF_TESTMODE
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilterTest"
!else
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilter"
!endif
  SetRegView 64
SectionEnd
