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
; T15: the installed-detection source is the same key Section Install writes.
; The test build uses the isolated HKCU test key (never the production one).
!ifdef FAF_TESTMODE
  InstallDirRegKey HKCU "Software\FreeAssetFilterTest" "InstallDir"
!else
  InstallDirRegKey HKCU "Software\FreeAssetFilter" "InstallDir"
!endif
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
; H5: bounded wait for the GUI's FIRST visible window. Together with the Exec
; error check this turns "process started but never produced a UI" into a fast,
; nonzero failure instead of a 30-minute silent wait. Seen-window liveness keeps
; the existing 3s grace and total timeout.
!ifndef FAF_GUI_WINDOW_DETECT_MS
  !define FAF_GUI_WINDOW_DETECT_MS 10000
!endif

; T15 maintenance handoff. Strings mirror src/render/maintenance_protocol.h; NSIS
; cannot include the C++ header. Mutexes are per-session Local\ objects. The test
; build gets its own names so it can never collide with a real setup / real UI.
!ifdef FAF_TESTMODE
  !define SETUP_MUTEX "Local\FreeAssetFilterSetupMutex.Test"
  !define MAINTENANCE_MUTEX "Local\FreeAssetFilterMaintenanceMutex.Test"
!else
  !define SETUP_MUTEX "Local\FreeAssetFilterSetupMutex"
  !define MAINTENANCE_MUTEX "Local\FreeAssetFilterMaintenanceMutex"
!endif

; D13/F2 shortcut isolation (mirrors maintenance_protocol.h::kShortcutStem*).
; Production: desktop FreeAssetFilter.lnk + Start Menu folder
; FreeAssetFilter\FreeAssetFilter.lnk. Test: flat FreeAssetFilterTest.lnk on both
; desktop and Start Menu; it must never create/delete/overwrite a production
; shortcut (including the legacy flat production Start Menu file).
!define SHORTCUT_STEM_PROD "FreeAssetFilter"
!ifdef FAF_TESTMODE
  !define SHORTCUT_STEM_TEST "FreeAssetFilterTest"
  !define SHORTCUT_STEM "${SHORTCUT_STEM_TEST}"
!else
  !define SHORTCUT_STEM "${SHORTCUT_STEM_PROD}"
!endif

; maintenance-decision.ini lives in the install dir (maintenance_protocol.h).
; The GUI writes schema first and `action` last; setup writes `ack=1` only after
; observing a non-empty action. A GUI-less wait may not be judged dead until it
; has been seen once (same liveness latch as the install-result wait below).
!define DECISION_SECTION "maintenance"
!define DECISION_KEY_ACTION "action"
!define DECISION_KEY_ACK "ack"
!ifndef FAF_DECISION_TIMEOUT_MS
  !define FAF_DECISION_TIMEOUT_MS 1800000
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

; T15 setup-owned state. The mutex handle is closed explicitly before every
; Quit/Abort path (normal success keeps it until process exit by design).
Var /GLOBAL SetupMutexHandle
Var /GLOBAL SetupPid
Var /GLOBAL GuiTempDir
Var /GLOBAL GuiTempExe
Var /GLOBAL DecisionIni

; T17 staged uninstall protocol. Strings mirror uninstall_protocol.h and
; render/maintenance_protocol.h; NSIS cannot include the C++ headers. Test builds
; get an isolated engine mutex and user-data root so they can never touch a real
; uninstall or the production profile.
!ifdef FAF_TESTMODE
  !define UNINSTALL_ENGINE_MUTEX "Local\FreeAssetFilterUninstallEngineMutex.Test"
  !define UNINSTALL_DATA_ROOT "$LOCALAPPDATA\FreeAssetFilterTestUserData"
!else
  !define UNINSTALL_ENGINE_MUTEX "Local\FreeAssetFilterUninstallEngineMutex"
  !define UNINSTALL_DATA_ROOT "$LOCALAPPDATA\FreeAssetFilter"
!endif
!define UNINSTALL_SECTION "uninstall"
!define UNINSTALL_REQUEST_FILE "uninstall-request.ini"
!define UNINSTALL_RESULT_FILE "uninstall-result.ini"
; Production defaults match maintenance_protocol.h. QA may override any of these
; on the makensis command line (for example a 6s request timeout to exercise the
; launcher cancellation path without waiting 30 minutes).
!ifndef FAF_UNINSTALL_REQUEST_TIMEOUT_MS
  !define FAF_UNINSTALL_REQUEST_TIMEOUT_MS 1800000
!endif
!ifndef FAF_UNINSTALL_UI_DONE_TIMEOUT_MS
  !define FAF_UNINSTALL_UI_DONE_TIMEOUT_MS 60000
!endif
!ifndef FAF_UNINSTALL_UI_PROCESS_WAIT_MS
  !define FAF_UNINSTALL_UI_PROCESS_WAIT_MS 10000
!endif
!ifndef FAF_UNINSTALL_SETUP_MUTEX_WAIT_MS
  !define FAF_UNINSTALL_SETUP_MUTEX_WAIT_MS 15000
!endif
!ifndef FAF_UNINSTALL_POLL_MS
  !define FAF_UNINSTALL_POLL_MS 200
!endif
; QA-only extra arguments appended to the UI command line by the launcher path.
; Empty in every normal test build; a QA build may pass e.g.
; -DFAF_QA_UI_EXTRA="/auto:page=6 /auto:action=uninstall". Never defined for
; production. T20 also reads FAF_QA_UI_RUNTIME_EXTRA at launch time so one test
; setup can exercise both delete_user_data=0 and =1 without rebuilding.
!ifdef FAF_TESTMODE
  !ifndef FAF_QA_UI_EXTRA
    !define FAF_QA_UI_EXTRA ""
  !endif
!endif

Var /GLOBAL UnEngineMutex
Var /GLOBAL UnRequestIni
Var /GLOBAL UnResultIni
Var /GLOBAL UnUiExe
Var /GLOBAL UnUiPid
Var /GLOBAL UnUiProcess
Var /GLOBAL UnUiExpected
Var /GLOBAL UnDeleteUserData
Var /GLOBAL UnHelperPid
Var /GLOBAL UnWarning
Var /GLOBAL UnErrorText
Var /GLOBAL UnFailedPath
Var /GLOBAL UnTarget
Var /GLOBAL UnFafDataDir

Var /GLOBAL UnArgMode
Var /GLOBAL UnArgInstallDir
Var /GLOBAL UnArgUi
Var /GLOBAL UnArgOrigSid
Var /GLOBAL UnArgOrigLocalAppData
Var /GLOBAL UnArgSilent

; T15 helper: close the setup mutex before Quit/Abort. Normal success intentionally
; keeps it until process exit (setup owns it from .onInit to process end).
Function CloseSetupMutex
  StrCmp $SetupMutexHandle "" closeSetupDone
  System::Call 'kernel32::CloseHandle(p $SetupMutexHandle)'
  StrCpy $SetupMutexHandle ""
closeSetupDone:
FunctionEnd

; T15 helper: activate the already-running GUI. A second setup may arrive before
; the first one has created its window, so poll briefly instead of failing fast.
Function ActivateExistingGui
  StrCpy $0 0
activateLoop:
  FindWindow $1 "FreeAssetFilterInstaller" ""
  StrCmp $1 0 0 activateFound
  IntCmp $0 5000 activateDone 0 activateDone
  Sleep 100
  IntOp $0 $0 + 100
  Goto activateLoop
activateFound:
  System::Call 'user32::ShowWindow(p $1, i 9)' ; SW_RESTORE
  System::Call 'user32::SetForegroundWindow(p $1)'
activateDone:
FunctionEnd

; M1: recursively delete one stale maintenance copy. $R5 = root directory.
; Reparse points are skipped (never traversed) and every failure is ignored:
; stale-copy cleanup is best effort and must never abort a new setup.
Function SweepDeleteTree
  StrCmp $R5 "" sweepTreeDone
  ClearErrors
  FindFirst $0 $1 "$R5\*.*"
  StrCmp $0 0 sweepTreeNoEntries
sweepTreeLoop:
  StrCmp $1 "" sweepTreeClose
  StrCmp $1 "." sweepTreeNext
  StrCmp $1 ".." sweepTreeNext
  System::Call 'kernel32::GetFileAttributesW(w "$R5\$1") i .r2'
  StrCmp $2 -1 sweepTreeNext
  IntOp $3 $2 & 0x400
  StrCmp $3 0 sweepTreeNotReparse
  Goto sweepTreeNext
sweepTreeNotReparse:
  IntOp $3 $2 & 0x10
  StrCmp $3 0 sweepTreeFile
  Push $R5
  Push $0
  Push $1
  StrCpy $R5 "$R5\$1"
  Call SweepDeleteTree
  Pop $1
  Pop $0
  Pop $R5
  Goto sweepTreeNext
sweepTreeFile:
  ClearErrors
  Delete "$R5\$1"
sweepTreeNext:
  FindNext $0 $1
  Goto sweepTreeLoop
sweepTreeClose:
  FindClose $0
sweepTreeNoEntries:
  ClearErrors
  RMDir "$R5"
sweepTreeDone:
FunctionEnd

; M1: remove maintenance GUI copies left behind by a setup/UI that died before
; cleanup. Runs after both single-instance mutexes are clear and before
; InitPluginsDir/PrepareGuiCopy creates this setup's own copy. Only exact
; $TEMP\FreeAssetFilterMaintenance-<digits> directories are considered:
; non-directories, reparse points and paths younger than 24h are skipped.
; Age is an exact 64-bit FILETIME comparison, not a calendar-day check.
Function SweepStaleGuiCopies
  ClearErrors
  FindFirst $9 $8 "$TEMP\FreeAssetFilterMaintenance-*"
  StrCmp $9 0 sweepDone
sweepLoop:
  StrCmp $8 "" sweepClose
  ; Leaf must be exactly the prefix followed by one or more ASCII digits.
  StrCpy $7 $8 27
  StrCmp $7 "FreeAssetFilterMaintenance-" 0 sweepNext
  StrCpy $7 $8 "" 27
  StrCmp $7 "" sweepNext
  StrLen $6 $7
  StrCpy $5 0
sweepDigitLoop:
  IntCmp $5 $6 sweepAttributes 0 sweepAttributes
  StrCpy $4 $7 1 $5
  StrCmp $4 "0" sweepDigitOk
  StrCmp $4 "1" sweepDigitOk
  StrCmp $4 "2" sweepDigitOk
  StrCmp $4 "3" sweepDigitOk
  StrCmp $4 "4" sweepDigitOk
  StrCmp $4 "5" sweepDigitOk
  StrCmp $4 "6" sweepDigitOk
  StrCmp $4 "7" sweepDigitOk
  StrCmp $4 "8" sweepDigitOk
  StrCmp $4 "9" sweepDigitOk
  Goto sweepNext
sweepDigitOk:
  IntOp $5 $5 + 1
  Goto sweepDigitLoop
sweepAttributes:
  System::Alloc 36
  Pop $R9
  System::Call 'kernel32::GetFileAttributesExW(w "$TEMP\$8", i 0, p $R9) i .r1'
  StrCmp $1 0 sweepFreeNext
  ; WIN32_FILE_ATTRIBUTE_DATA: attrs, creation(2), access(2), write(2).
  ; Read through lastWrite only so $8 (name) / $9 (find handle) survive.
  System::Call '*$R9(i .r1, i .r2, i .r3, i .r4, i .r5, i .r6, i .r7)'
  System::Free $R9
  IntOp $R1 $1 & 0x10
  StrCmp $R1 0 sweepNext
  IntOp $R1 $1 & 0x400
  StrCmp $R1 0 0 sweepNext
  ; Reconstruct FILETIME with unsigned DWORDs (System `i` is signed 32-bit).
  System::Int64Op $6 & 0xFFFFFFFF
  Pop $6
  System::Int64Op $7 & 0xFFFFFFFF
  Pop $7
  System::Int64Op $7 << 32
  Pop $7
  System::Int64Op $7 | $6
  Pop $7
  System::Alloc 8
  Pop $R9
  System::Call 'kernel32::GetSystemTimeAsFileTime(p $R9)'
  System::Call '*$R9(i .r2, i .r3)'
  System::Free $R9
  System::Int64Op $2 & 0xFFFFFFFF
  Pop $2
  System::Int64Op $3 & 0xFFFFFFFF
  Pop $3
  System::Int64Op $3 << 32
  Pop $3
  System::Int64Op $3 | $2
  Pop $3
  System::Int64Op $3 - $7
  Pop $R3
  ; 24h in 100ns units = 864000000000; keep anything younger.
  System::Int64Op $R3 < 864000000000
  Pop $6
  StrCmp $6 1 sweepNext
  StrCpy $R5 "$TEMP\$8"
  Call SweepDeleteTree
  Goto sweepNext
sweepFreeNext:
  System::Free $R9
  Goto sweepNext
sweepNext:
  FindNext $9 $8
  Goto sweepLoop
sweepClose:
  FindClose $9
sweepDone:
FunctionEnd

; T15 helper: extract the GUI + runtime DLL from $PLUGINSDIR into a setup-owned
; temp copy. The GUI may outlive this setup (maintenance uninstall/cancel), so
; Exec must never depend on $PLUGINSDIR staying alive.
Function PrepareGuiCopy
  System::Call 'kernel32::GetCurrentProcessId() i.r0'
  StrCpy $SetupPid $0
  StrCpy $GuiTempDir "$TEMP\FreeAssetFilterMaintenance-$SetupPid"
  CreateDirectory "$GuiTempDir"
  CopyFiles /SILENT "$PLUGINSDIR\FreeAssetFilterInstaller.exe" "$GuiTempDir"
  CopyFiles /SILENT "$PLUGINSDIR\libwinpthread-1.dll" "$GuiTempDir"
  StrCpy $GuiTempExe "$GuiTempDir\FreeAssetFilterInstaller.exe"
  IfFileExists "$GuiTempExe" 0 guiCopyFailed
  IfFileExists "$GuiTempDir\libwinpthread-1.dll" 0 guiCopyFailed
  Return
guiCopyFailed:
  ; Never launch a GUI that cannot load its MinGW runtime.
  SetErrorLevel 2
  Call CloseSetupMutex
  Abort
FunctionEnd

; T15 helper: same payload release + sentinel as the pre-T15 fresh-install flow.
Function ReleasePayload
  SetOutPath "$PLUGINSDIR\payload"
  File /r "${PAYLOAD}\*"
  ; Payload-ready sentinel: written AFTER the payload release above completes and
  ; OUTSIDE the payload directory. The GUI waits for this before pre-scanning and
  ; copying. WriteINIStr takes 4 parameters: file / section / key / value.
  WriteINIStr "$PLUGINSDIR\payload.ready" "ready" "ready" "1"
FunctionEnd

; T15 helper: the unchanged install-result wait. Readiness is a non-empty terminal
; `abort` key, never mere file existence. `dir` is written back only after that.
Function WaitForInstallResult
  StrCpy $Seen 0
  StrCpy $2 0        ; elapsed ms
  StrCpy $3 0        ; consecutive ticks with the window gone after first sight
waitLoop:
  IfFileExists "${RESULT_INI}" 0 waitLiveness
  ReadINIStr $0 "${RESULT_INI}" "install" "abort"
  StrCmp $0 "" 0 waitDone
waitLiveness:
  FindWindow $R0 "FreeAssetFilterInstaller" ""
  StrCmp $R0 0 0 waitAlive
  ; Window not found: only judgeable once it has been seen at least once.
  StrCmp $Seen 1 0 waitNoWindowCheck
  IntOp $3 $3 + 1
  IntCmp $3 30 waitCrash 0 waitCrash
  Goto waitTick
waitNoWindowCheck:
  ; H5: first-window deadline. A process that never shows a UI (blocked before
  ; window creation, silent crash, wrong image) fails fast and nonzero.
  IntCmp $2 ${FAF_GUI_WINDOW_DETECT_MS} waitNoWindow waitTick waitNoWindow
waitAlive:
  StrCpy $Seen 1
  StrCpy $3 0
waitTick:
  Sleep 100
  IntOp $2 $2 + 100
  IntCmp $2 ${FAF_WAIT_TIMEOUT_MS} 0 0 waitTimeout
  Goto waitLoop
waitTimeout:
  ; Bounded fallback: no terminal key within FAF_WAIT_TIMEOUT_MS -> silent abort.
  Call CloseSetupMutex
  Abort
waitNoWindow:
  ; H5: Exec succeeded but no installer window appeared within the deadline.
  SetErrorLevel 4
  Call CloseSetupMutex
  Abort
waitCrash:
  ; The GUI window vanished after being seen without a terminal key -> GUI died
  ; (short grace above covers final INI flushes). Silent, bounded abort.
  Call CloseSetupMutex
  Abort
waitDone:
  ; `dir` write-back strictly AFTER the terminal key is confirmed (before it,
  ; $INSTDIR would still hold the default / /installdir prefill value).
  ReadINIStr $0 "${RESULT_INI}" "install" "dir"
  StrCmp $0 "" waitDirDone
  StrCpy $INSTDIR $0
waitDirDone:
  ReadINIStr $0 "${RESULT_INI}" "install" "abort"
  StrCmp $0 "1" 0 waitProceed
  Call CloseSetupMutex
  Abort
waitProceed:
  Return
FunctionEnd

Function .onInit
  ; T15: one setup owns the machine/session-wide setup mutex. A second setup must
  ; activate the existing GUI and leave without touching the payload or registry.
  ; CreateMutexW returns ERROR_ALREADY_EXISTS in the `?e` stack slot; the returned
  ; handle must be closed in that case (we did not create the object).
  System::Call 'kernel32::CreateMutexW(p 0, i 0, w "${SETUP_MUTEX}") p .r1 ?e'
  Pop $0
  StrCmp $1 0 setupMutexFailed
  StrCmp $0 183 setupAlreadyRunning 0
  StrCpy $SetupMutexHandle $1

  ; A maintenance UI may already exist even when no setup is running (the setup
  ; releases its mutex after the handoff). Never let two maintenance UIs race.
  ; OpenMutexW(SYNCHRONIZE) + ERROR_ACCESS_DENIED means the object exists but the
  ; current token cannot open it -> still treat it as held.
  System::Call 'kernel32::OpenMutexW(i 0x00100000, i 0, w "${MAINTENANCE_MUTEX}") p .r1 ?e'
  Pop $0
  StrCmp $1 0 0 maintenanceMutexOpen
  StrCmp $0 5 maintenanceMutexHeld 0
  Goto setupMutexAcquired
maintenanceMutexOpen:
  System::Call 'kernel32::CloseHandle(p $1)'
maintenanceMutexHeld:
  Call ActivateExistingGui
  Call CloseSetupMutex
  Quit

setupMutexFailed:
  ; Cannot establish single-instance ownership -> refuse to run rather than risk
  ; two setup processes extracting the same payload.
  SetErrorLevel 3
  Quit

setupAlreadyRunning:
  ; We only opened the existing mutex; close our duplicate before activating.
  System::Call 'kernel32::CloseHandle(p $1)'
  Call ActivateExistingGui
  Quit

setupMutexAcquired:
  ; F1/C2: the setup mutex is released before the uninstall helper exits, so a
  ; second setup can otherwise slip in while a staged uninstall still owns the
  ; engine mutex and race its payload extraction. Check the uninstall engine
  ; mutex BEFORE InitPluginsDir and hand off to the existing GUI when held.
  ; OpenMutexW(SYNCHRONIZE) + ERROR_ACCESS_DENIED (5) still means "exists".
  ; $R1 is safe to reuse here (the setup-mutex handle is already in
  ; $SetupMutexHandle).
  System::Call 'kernel32::OpenMutexW(i 0x00100000, i 0, w "${UNINSTALL_ENGINE_MUTEX}") p .r1 ?e'
  Pop $0
  StrCmp $1 0 0 engineMutexOpen
  StrCmp $0 5 engineMutexHeld 0
  Goto engineMutexClear
engineMutexOpen:
  System::Call 'kernel32::CloseHandle(p $1)'
engineMutexHeld:
  Call ActivateExistingGui
  Call CloseSetupMutex
  Quit

engineMutexClear:
  ; M1: sweep stale maintenance copies only after ownership is established and
  ; before this setup creates its own copy (never touches $PLUGINSDIR).
  Call SweepStaleGuiCopies
  InitPluginsDir
  SetOutPath "$PLUGINSDIR"
  ; GUI binary. Test branch embeds the FAF_TESTMODE build from
  ; tools/build_test_gui.ps1 (repo-root build/test-installer, a separate output
  ; dir from the production build/installer artifact). Production branch
  ; unchanged. The MinGW runtime follows the same branch.
!ifdef FAF_TESTMODE
  File "..\build\test-installer\FreeAssetFilterInstaller.exe"
  File "..\build\test-installer\libwinpthread-1.dll"
!else
  File "..\build\installer\FreeAssetFilterInstaller.exe"
  File "..\build\installer\libwinpthread-1.dll"
!endif
  Call PrepareGuiCopy

  ; T15 installed detection is exactly: app exe OR _internal. No other signal
  ; (result INI, shortcuts, Add/Remove entry) may force maintenance mode.
  IfFileExists "$INSTDIR\FreeAssetFilter.exe" installed 0
  IfFileExists "$INSTDIR\_internal" installed 0

  ; Fresh install: behavior is unchanged. The only difference is that the GUI
  ; now runs from the temp copy (with libwinpthread-1.dll next to it).
  ; Test branch drives the GUI unattended: /auto:opts=<bits> (contract §17)
  ; automates 欢迎→…→完成 with the frozen option bits (default 1101);
  ; production branch stays interactive (no /auto flag).
!ifdef FAF_TESTMODE
  ; T20 runtime override: FAF_QA_INSTALL_OPTS lets one test setup install with
  ; option bits that avoid touching the real desktop/start-menu (e.g. 0000).
  ; Empty/unset keeps the frozen FAF_AUTO_PROFILE contract.
  ReadEnvStr $R3 "FAF_QA_INSTALL_OPTS"
  StrCmp $R3 "" 0 installOptsReady
  StrCpy $R3 "${FAF_AUTO_PROFILE}"
installOptsReady:
  ClearErrors
  Exec '"$GuiTempExe" /payload "$PLUGINSDIR\payload" /result "${RESULT_INI}" /installdir "$INSTDIR" /auto:opts=$R3'
!else
  ClearErrors
  Exec '"$GuiTempExe" /payload "$PLUGINSDIR\payload" /result "${RESULT_INI}" /installdir "$INSTDIR"'
!endif
  ; H3/F1: a refused Exec (missing image, ACL, AV) has no error code of its own;
  ; without this it fell through to the liveness wait and exited 0 after 10s.
  IfErrors guiLaunchFailed
  Call ReleasePayload
  Call WaitForInstallResult
  Return

guiLaunchFailed:
  SetErrorLevel 4
  Call CloseSetupMutex
  Abort

installed:
  ; Maintenance handoff: GUI writes action last, setup writes ack=1 afterwards.
  ; Never infer readiness from the file's existence - only a non-empty `action`.
  StrCpy $DecisionIni "$INSTDIR\maintenance-decision.ini"
  Delete "$DecisionIni"
!ifdef FAF_TESTMODE
  ; T20 runtime hook: /auto:mode=maintenance + action for unattended QA.
  ReadEnvStr $R2 "FAF_QA_MAINTENANCE_EXTRA"
  ClearErrors
  Exec '"$GuiTempExe" /maintenance /payload "$PLUGINSDIR\payload" /result "${RESULT_INI}" /installdir "$INSTDIR" /decision "$DecisionIni" /setup-pid $SetupPid $R2'
!else
  ClearErrors
  Exec '"$GuiTempExe" /maintenance /payload "$PLUGINSDIR\payload" /result "${RESULT_INI}" /installdir "$INSTDIR" /decision "$DecisionIni" /setup-pid $SetupPid'
!endif
  ; H3/F1: same fail-fast as the fresh-install Exec. No process -> no decision
  ; file can ever appear, so waiting would just burn the 30-minute timeout.
  IfErrors maintenanceLaunchFailed
  StrCpy $Seen 0
  StrCpy $2 0        ; elapsed ms
  StrCpy $3 0        ; consecutive ticks with the window gone after first sight
decisionLoop:
  IfFileExists "$DecisionIni" 0 decisionLiveness
  ReadINIStr $0 "$DecisionIni" "${DECISION_SECTION}" "${DECISION_KEY_ACTION}"
  StrCmp $0 "" 0 decisionReady
decisionLiveness:
  FindWindow $R0 "FreeAssetFilterInstaller" ""
  StrCmp $R0 0 0 decisionAlive
  ; Not-yet-seen is not a failure; seen-then-gone without action is.
  StrCmp $Seen 1 0 decisionNoWindowCheck
  IntOp $3 $3 + 1
  IntCmp $3 30 decisionGuiGone 0 decisionGuiGone
  Goto decisionTick
decisionNoWindowCheck:
  ; H5: same first-window deadline as WaitForInstallResult (200ms ticks).
  IntCmp $2 ${FAF_GUI_WINDOW_DETECT_MS} decisionNoWindow decisionTick decisionNoWindow
decisionAlive:
  StrCpy $Seen 1
  StrCpy $3 0
decisionTick:
  Sleep 200
  IntOp $2 $2 + 200
  IntCmp $2 ${FAF_DECISION_TIMEOUT_MS} 0 0 decisionTimeout
  Goto decisionLoop
decisionNoWindow:
  ; H5: Exec succeeded but the maintenance UI never appeared.
  SetErrorLevel 4
  Call CloseSetupMutex
  Abort
decisionTimeout:
decisionGuiGone:
  ; No decision (timeout or GUI died after being seen): do not unpack payload.
  Call CloseSetupMutex
  Abort
decisionReady:
  StrCmp $0 "repair" 0 decisionNonRepair
  ; repair: ack FIRST, then release payload + sentinel, then the unchanged
  ; install-result wait (repair success lets Section Install refresh metadata).
  ClearErrors
  WriteINIStr "$DecisionIni" "${DECISION_SECTION}" "${DECISION_KEY_ACK}" "1"
  IfErrors decisionAckFailed
  Call ReleasePayload
  Call WaitForInstallResult
  Return
decisionNonRepair:
  ; uninstall / cancel (and any unexpected non-repair value): ack, release the
  ; setup mutex, and leave immediately. Never unpack payload or run Section Install.
  ClearErrors
  WriteINIStr "$DecisionIni" "${DECISION_SECTION}" "${DECISION_KEY_ACK}" "1"
  IfErrors decisionAckFailed
  Call CloseSetupMutex
  Abort
decisionAckFailed:
  Call CloseSetupMutex
  Abort
maintenanceLaunchFailed:
  ; H3: no GUI process means no decision can ever be written.
  SetErrorLevel 4
  Call CloseSetupMutex
  Abort
FunctionEnd

; ===========================================================================
; T17 uninstaller helpers and staged engine
; ===========================================================================
; All result writes are followed by a profile flush so the UI (a different
; process) sees the terminal key immediately. The C++ side precreates its INI
; with a UTF-16LE BOM; NSIS writes UTF-8/ANSI, which GetPrivateProfileStringW
; reads correctly, so no NSIS-side BOM is needed (and would corrupt the first
; section header if written as raw bytes).
Function un.FlushResult
  StrCmp $UnResultIni "" unFlushDone
  System::Call 'kernel32::WritePrivateProfileStringW(p 0, p 0, p 0, w "$UnResultIni")'
unFlushDone:
FunctionEnd

Function un.WriteStarted
  StrCmp $UnResultIni "" unStartedDone
  WriteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "schema" "1"
  WriteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "stage" "started"
  WriteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "permille" "0"
  WriteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "error" ""
  DeleteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "warning"
  DeleteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "done"
  Call un.FlushResult
unStartedDone:
FunctionEnd

; $0 = stage, $1 = permille. Never touches the terminal done key.
Function un.WriteProgress
  StrCmp $UnResultIni "" unProgressDone
  WriteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "schema" "1"
  WriteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "stage" "$0"
  WriteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "permille" "$1"
  Call un.FlushResult
unProgressDone:
FunctionEnd

; Failure terminal writer. Uses $UnErrorText; writes done last.
Function un.WriteFailed
  StrCmp $UnResultIni "" unFailedDone
  WriteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "schema" "1"
  WriteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "stage" "failed"
  WriteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "permille" "0"
  WriteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "error" "$UnErrorText"
  StrCmp $UnWarning "" 0 unFailedWarning
  DeleteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "warning"
  Goto unFailedWriteDone
unFailedWarning:
  WriteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "warning" "$UnWarning"
unFailedWriteDone:
  WriteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "done" "1"
  Call un.FlushResult
  SetErrorLevel 1
unFailedDone:
FunctionEnd

; Cancellation terminal writer. Must not delete any file.
Function un.WriteCancelled
  StrCmp $UnResultIni "" unCancelledDone
  WriteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "schema" "1"
  WriteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "stage" "cancelled"
  WriteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "permille" "0"
  WriteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "error" ""
  StrCmp $UnWarning "" 0 unCancelledWarning
  DeleteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "warning"
  Goto unCancelledWriteDone
unCancelledWarning:
  WriteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "warning" "$UnWarning"
unCancelledWriteDone:
  WriteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "done" "1"
  Call un.FlushResult
  SetErrorLevel 1
unCancelledDone:
FunctionEnd

; Success terminal writer. done=1 is written LAST (C1/M2): the UI's Finish page
; observes it and only then writes ui_done=1. Never wait for ui_done before this.
Function un.WriteDone
  StrCmp $UnResultIni "" unDoneDone
  WriteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "schema" "1"
  WriteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "stage" "done"
  WriteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "permille" "1000"
  DeleteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "error"
  StrCmp $UnWarning "" 0 unDoneWarning
  DeleteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "warning"
  Goto unDoneWriteDone
unDoneWarning:
  WriteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "warning" "$UnWarning"
unDoneWriteDone:
  WriteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "done" "1"
  Call un.FlushResult
unDoneDone:
FunctionEnd

; Append a warning token (semicolon-separated), avoiding duplicate writes.
; $0 = token.
Function un.AddWarning
  StrCmp $UnWarning "" unAddWarningSet
  StrCpy $UnWarning "$UnWarning;$0"
  Return
unAddWarningSet:
  StrCpy $UnWarning "$0"
FunctionEnd

; Strip trailing backslashes from $R5 (keeps drive roots usable for prefix
; comparison; "C:\" becomes "C:" and still prefix-matches "C:\x").
Function un.StripTrailingSlash
unStripLoop:
  StrCpy $0 $R5 1 -1
  StrCmp $0 "\" 0 unStripDone
  StrCpy $R5 $R5 -1
  Goto unStripLoop
unStripDone:
FunctionEnd

; $R5 = base, $R6 = candidate -> $R7 = 1 when candidate equals base or is a
; descendant. StrCmp is case-insensitive, matching Windows path semantics.
Function un.IsPathInside
  StrCpy $R7 0
  StrCmp $R5 "" unInsideDone
  StrCmp $R6 "" unInsideDone
  StrLen $0 $R5
  StrCpy $1 $R6 $0
  StrCmp $1 $R5 0 unInsideDone
  StrCmp $R6 $R5 unInsideYes
  StrCpy $1 $R6 1 $0
  StrCmp $1 "\" unInsideYes
  Goto unInsideDone
unInsideYes:
  StrCpy $R7 1
unInsideDone:
FunctionEnd

; $R5 = base, $R6 = candidate -> $R7 = 1 when either path contains the other.
; Used to avoid deleting a target that contains a custom FAF_DATA_DIR (or is
; contained by it).
Function un.PathsOverlap
  Push $R5
  Push $R6
  Call un.IsPathInside
  StrCmp $R7 1 unOverlapYes
  Pop $R6
  Pop $R5
  StrCpy $0 $R5
  StrCpy $R5 $R6
  StrCpy $R6 $0
  Call un.IsPathInside
  StrCmp $R7 1 unOverlapYesNoPush
  StrCpy $R7 0
  Return
unOverlapYesNoPush:
  StrCpy $R7 1
  Return
unOverlapYes:
  Pop $R6
  Pop $R5
  StrCpy $R7 1
FunctionEnd

; Recursive delete. $R5 = root, $R6 = top-level child name to skip ("" for
; none), $R8 = 1 to treat a remaining root as failure. Failure path is stored in
; $UnFailedPath. Reparse points are skipped rather than traversed.
Function un.DeleteTree
  StrCpy $UnFailedPath ""
  StrCmp $R5 "" unTreeDone
  FindFirst $0 $1 "$R5\*.*"
  StrCmp $0 0 unTreeNoEntries
unTreeLoop:
  StrCmp $1 "" unTreeClose
  StrCmp $1 "." unTreeNext
  StrCmp $1 ".." unTreeNext
  StrCmp $R6 "" unTreeCheck
  StrCmp $1 $R6 unTreeNext
unTreeCheck:
  System::Call 'kernel32::GetFileAttributesW(w "$R5\$1") i .r2'
  IntOp $3 $2 & 0x400
  StrCmp $3 0 unTreeNotReparse
  Goto unTreeNext
unTreeNotReparse:
  IntOp $3 $2 & 0x10
  StrCmp $3 0 unTreeFile
  Push $R5
  Push $R6
  Push $R8
  Push $0
  Push $1
  StrCpy $R5 "$R5\$1"
  StrCpy $R6 ""
  StrCpy $R8 1
  Call un.DeleteTree
  Pop $1
  Pop $0
  Pop $R8
  Pop $R6
  Pop $R5
  StrCmp $UnFailedPath "" 0 unTreeClose
  Goto unTreeNext
unTreeFile:
  ClearErrors
  Delete "$R5\$1"
  IfErrors unTreeFileFail
  IfFileExists "$R5\$1" unTreeFileFail
  Goto unTreeNext
unTreeFileFail:
  StrCpy $UnFailedPath "$R5\$1"
  Goto unTreeClose
unTreeNext:
  FindNext $0 $1
  Goto unTreeLoop
unTreeClose:
  FindClose $0
  StrCmp $UnFailedPath "" 0 unTreeDone
  Goto unTreeRoot
unTreeRoot:
  RMDir "$R5"
  IfFileExists "$R5" 0 unTreeDone
  StrCmp $R8 "0" 0 unTreeRootFail
  ; A scanned tree whose root remains is either a skipped user-data child
  ; (R8=0) or an unexpected failure. For R8=0 the install-dir warning covers it.
  Goto unTreeDone
unTreeRootFail:
  StrCpy $UnFailedPath "$R5"
  Goto unTreeDone
unTreeNoEntries:
  ; FindFirst returning no handle means the directory is empty (or unreadable).
  RMDir "$R5"
  IfFileExists "$R5" unTreeRootFail
unTreeDone:
FunctionEnd

; M1: after the UI has exited, remove the setup-owned maintenance copy it ran
; from. Only an exact $TEMP\FreeAssetFilterMaintenance-<digits> parent is
; eligible; $INSTDIR, $PLUGINSDIR and every other path are refused. The UI may
; already have self-cleaned (its cleanup is asynchronous), so a missing
; directory is a normal no-op.
Function un.CleanupUiTempDir
  StrCmp $UnUiExe "" unCleanupTempDone
  ; Parent of $UnUiExe (same result as ${GetParent}, without depending on the
  ; macro's installer/uninstaller function-prefix expansion).
  StrLen $1 $UnUiExe
  IntOp $1 $1 - 1
unCleanupTempSep:
  IntCmp $1 0 unCleanupTempDone 0 unCleanupTempDone
  StrCpy $2 $UnUiExe 1 $1
  StrCmp $2 "\" unCleanupTempSepFound
  IntOp $1 $1 - 1
  Goto unCleanupTempSep
unCleanupTempSepFound:
  StrCpy $0 $UnUiExe $1
  StrCmp $0 "" unCleanupTempDone
  StrCmp $0 "$INSTDIR" unCleanupTempDone
  StrCmp $0 "$PLUGINSDIR" unCleanupTempDone
  StrCpy $1 "$TEMP\FreeAssetFilterMaintenance-"
  StrLen $2 $1
  StrCpy $3 $0 $2
  StrCmp $3 $1 0 unCleanupTempDone
  StrCpy $4 $0 "" $2
  StrCmp $4 "" unCleanupTempDone
  StrLen $5 $4
  StrCpy $6 0
unCleanupTempDigit:
  IntCmp $6 $5 unCleanupTempShape 0 unCleanupTempShape
  StrCpy $7 $4 1 $6
  StrCmp $7 "0" unCleanupTempDigitOk
  StrCmp $7 "1" unCleanupTempDigitOk
  StrCmp $7 "2" unCleanupTempDigitOk
  StrCmp $7 "3" unCleanupTempDigitOk
  StrCmp $7 "4" unCleanupTempDigitOk
  StrCmp $7 "5" unCleanupTempDigitOk
  StrCmp $7 "6" unCleanupTempDigitOk
  StrCmp $7 "7" unCleanupTempDigitOk
  StrCmp $7 "8" unCleanupTempDigitOk
  StrCmp $7 "9" unCleanupTempDigitOk
  Goto unCleanupTempDone
unCleanupTempDigitOk:
  IntOp $6 $6 + 1
  Goto unCleanupTempDigit
unCleanupTempShape:
  System::Call 'kernel32::GetFileAttributesW(w "$0") i .r1'
  StrCmp $1 -1 unCleanupTempDone
  IntOp $2 $1 & 0x10
  StrCmp $2 0 unCleanupTempDone
  IntOp $2 $1 & 0x400
  StrCmp $2 0 unCleanupTempDelete
  Goto unCleanupTempDone
unCleanupTempDelete:
  ; un.DeleteTree skips reparse points and is best-effort in this post-done path.
  StrCpy $R5 $0
  StrCpy $R6 ""
  StrCpy $R8 "0"
  Call un.DeleteTree
  StrCpy $UnFailedPath ""
unCleanupTempDone:
FunctionEnd

; Parse one whitespace-separated argument from $R0 into $R1; quoted arguments
; may contain spaces. $R0 is advanced past the consumed argument.
Function un.NextArg
  StrCpy $R1 ""
  StrCpy $R2 0
  StrCpy $R3 0
unNextScan:
  StrCpy $R4 $R0 1 $R3
  StrCmp $R4 "" unNextDone
  StrCmp $R4 " " unNextSpace
  StrCmp $R4 '"' unNextQuote
  StrCpy $R1 "$R1$R4"
  IntOp $R3 $R3 + 1
  Goto unNextScan
unNextQuote:
  IntOp $R3 $R3 + 1
unNextQuoteLoop:
  StrCpy $R4 $R0 1 $R3
  StrCmp $R4 "" unNextDone
  StrCmp $R4 '"' unNextQuoteEnd
  StrCpy $R1 "$R1$R4"
  IntOp $R3 $R3 + 1
  Goto unNextQuoteLoop
unNextQuoteEnd:
  IntOp $R3 $R3 + 1
  Goto unNextDone
unNextSpace:
  IntOp $R3 $R3 + 1
unNextDone:
  StrCpy $R0 $R0 "" $R3
FunctionEnd

; Wait for a complete request (or cancellation). UI liveness uses both the
; request's ui_pid (once known) and the window class before that. A missing
; window is only judged after it has been seen once. On cancel/timeout/UI death
; this writes stage=cancelled done=1, deletes nothing, and quits.
Function un.WaitForRequest
  StrCpy $0 0        ; elapsed
  StrCpy $1 0        ; consecutive gone ticks after first sight
  StrCpy $2 0        ; seen latch
unReqLoop:
  IfFileExists "$UnRequestIni" 0 unReqLiveness
  ReadINIStr $3 "$UnRequestIni" "${UNINSTALL_SECTION}" "schema"
  StrCmp $3 "1" 0 unReqLiveness
  ReadINIStr $3 "$UnRequestIni" "${UNINSTALL_SECTION}" "cancelled"
  StrCmp $3 "1" unReqCancelled
  ReadINIStr $4 "$UnRequestIni" "${UNINSTALL_SECTION}" "delete_user_data"
  StrCmp $4 "0" unReqFields
  StrCmp $4 "1" unReqFields
  Goto unReqLiveness
unReqFields:
  ReadINIStr $5 "$UnRequestIni" "${UNINSTALL_SECTION}" "ui_pid"
  ReadINIStr $6 "$UnRequestIni" "${UNINSTALL_SECTION}" "ui_exe"
  StrCmp $5 "" unReqLiveness
  StrCmp $6 "" unReqLiveness
  StrCpy $UnDeleteUserData $4
  StrCpy $UnUiPid $5
  StrCpy $UnUiExe $6
  System::Call 'kernel32::OpenProcess(i 0x00100000, i 0, i $UnUiPid) p .r0'
  StrCpy $UnUiProcess $0
  Return
unReqCancelled:
  StrCpy $UnWarning ""
  Call un.WriteCancelled
  Quit
unReqLiveness:
  ; Only the expected-UI paths (launcher / helper) may judge the UI dead.
  ; Silent mode (UnUiExpected=0) must keep waiting for a request/result it will
  ; never get. NOTE: StrCmp's third parameter is the EQUAL jump; this must be
  ; `0` so expected=1 falls through to the liveness check (the previous form
  ; jumped straight to the tick and never detected a killed UI).
  StrCmp $UnUiExpected "1" 0 unReqTick
  StrCmp $UnUiProcess 0 unReqFind
  System::Call 'kernel32::WaitForSingleObject(p $UnUiProcess, i 0) i .r7'
  StrCmp $7 0 unReqGone
  Goto unReqTick
unReqFind:
  FindWindow $R0 "FreeAssetFilterInstaller" ""
  StrCmp $R0 0 0 unReqSeen
  StrCmp $2 1 0 unReqTick
  IntOp $1 $1 + 1
  IntCmp $1 30 unReqGone 0 unReqGone
  Goto unReqTick
unReqSeen:
  StrCpy $2 1
  StrCpy $1 0
unReqTick:
  Sleep ${FAF_UNINSTALL_POLL_MS}
  IntOp $0 $0 + ${FAF_UNINSTALL_POLL_MS}
  IntCmp $0 ${FAF_UNINSTALL_REQUEST_TIMEOUT_MS} 0 0 unReqTimeout
  Goto unReqLoop
unReqTimeout:
unReqGone:
  StrCpy $UnWarning ""
  Call un.WriteCancelled
  Quit
FunctionEnd

; T17 entry point. Parses the mode/arguments, claims the engine + setup mutexes,
; establishes request/result paths, then either waits for the UI request or
; prepares the silent path before letting Section Uninstall run.
Function un.onInit
  ${GetParameters} $R0
  StrCpy $UnArgMode ""
  StrCpy $UnArgInstallDir ""
  StrCpy $UnArgUi ""
  StrCpy $UnArgOrigSid ""
  StrCpy $UnArgOrigLocalAppData ""
  StrCpy $UnArgSilent "0"
unArgLoop:
  StrCmp $R0 "" unArgDone
  Call un.NextArg
  StrCmp $R1 "" unArgLoop
  StrCmp $R1 "/uninstall-launcher" 0 unArgHelper
  StrCpy $UnArgMode "launcher"
  Goto unArgLoop
unArgHelper:
  StrCmp $R1 "/uninstall-helper" 0 unArgSilent
  StrCpy $UnArgMode "helper"
  Goto unArgLoop
unArgSilent:
  StrCmp $R1 "/S" 0 unArgInstall
  StrCpy $UnArgSilent "1"
  Goto unArgLoop
unArgInstall:
  StrCmp $R1 "/installdir" 0 unArgUi
  Call un.NextArg
  StrCpy $UnArgInstallDir $R1
  Goto unArgLoop
unArgUi:
  StrCmp $R1 "/ui" 0 unArgOrigSid
  Call un.NextArg
  StrCpy $UnArgUi $R1
  Goto unArgLoop
unArgOrigSid:
  StrCmp $R1 "/orig-sid" 0 unArgOrigLocal
  Call un.NextArg
  StrCpy $UnArgOrigSid $R1
  Goto unArgLoop
unArgOrigLocal:
  StrCmp $R1 "/orig-localappdata" 0 unArgIgnore
  Call un.NextArg
  StrCpy $UnArgOrigLocalAppData $R1
  Goto unArgLoop
unArgIgnore:
  Goto unArgLoop
unArgDone:
  StrCmp $UnArgInstallDir "" unArgDirDone
  StrCpy $INSTDIR $UnArgInstallDir
unArgDirDone:
  StrCpy $UnRequestIni "$INSTDIR\${UNINSTALL_REQUEST_FILE}"
  StrCpy $UnResultIni "$INSTDIR\${UNINSTALL_RESULT_FILE}"
  StrCpy $UnUiExe "$INSTDIR\FreeAssetFilterUninstall.exe"
  StrCmp $UnArgUi "" unArgUiDone
  StrCpy $UnUiExe $UnArgUi
unArgUiDone:
  StrCpy $UnUiExpected "0"
  StrCpy $UnDeleteUserData "0"
  StrCpy $UnUiPid ""
  StrCpy $UnUiProcess 0
  StrCpy $UnWarning ""
  StrCpy $UnErrorText ""
  StrCpy $UnFailedPath ""

  ; Engine mutex: create, then acquire with a zero-timeout wait. An abandoned
  ; previous mutex is recoverable (WAIT_ABANDONED); a live owner is not.
  System::Call 'kernel32::CreateMutexW(p 0, i 0, w "${UNINSTALL_ENGINE_MUTEX}") p .r1 ?e'
  Pop $0
  StrCmp $1 0 unEngineFail
  System::Call 'kernel32::WaitForSingleObject(p $1, i 0) i .r2'
  StrCmp $2 0 unEngineOwned
  StrCmp $2 128 unEngineOwned
  System::Call 'kernel32::CloseHandle(p $1)'
  Goto unEngineBusy
unEngineOwned:
  StrCpy $UnEngineMutex $1
  Goto unEngineDone
unEngineFail:
unEngineBusy:
  StrCpy $UnErrorText "engine-busy"
  Call un.WriteFailed
  Quit
unEngineDone:

  ; Setup mutex: OpenMutex missing => setup absent. Access denied or a live
  ; handle => wait up to 15s, then release ownership (if acquired) and close.
  ; Setup releases the mutex on ack before the uninstaller starts, so this is
  ; normally a no-op.
  ; CreateMutex (not OpenMutex) so a missing object is a successful zero-wait;
  ; the returned handle works for both the absent and already-running cases.
  System::Call 'kernel32::CreateMutexW(p 0, i 0, w "${SETUP_MUTEX}") p .r1'
  StrCmp $1 0 unSetupProceed
  System::Call 'kernel32::WaitForSingleObject(p $1, i ${FAF_UNINSTALL_SETUP_MUTEX_WAIT_MS}) i .r3'
  System::Call 'kernel32::CloseHandle(p $1)'
  StrCmp $3 0 unSetupProceed
  StrCmp $3 128 unSetupProceed
  StrCpy $UnErrorText "setup-busy"
  Call un.WriteFailed
  Quit

unSetupProceed:
  StrCmp $UnArgSilent "1" unSilent
  StrCmp $UnArgMode "launcher" unLauncher
  StrCmp $UnArgMode "helper" unHelper
  Goto unHelper

unSilent:
  ; QuietUninstallString or a missing UI: no confirmation, never delete user
  ; data implicitly.
  Delete "$UnRequestIni"
  Delete "$UnResultIni"
  StrCpy $UnUiExpected "0"
  StrCpy $UnDeleteUserData "0"
  Call un.WriteStarted
  Goto unOnInitDone

unLauncher:
  Delete "$UnRequestIni"
  Delete "$UnResultIni"
  StrCpy $UnUiExpected "1"
  StrCpy $UnDeleteUserData "0"
  IfFileExists "$UnUiExe" 0 unLauncherSilent
  Call un.WriteStarted
  System::Call 'kernel32::GetCurrentProcessId() i.r0'
  StrCpy $UnHelperPid $0
  StrCpy $3 '"$UnUiExe" /uninstall /installdir "$INSTDIR" /helper "$INSTDIR\UninstallHelper.exe" /helper-pid $UnHelperPid'
  StrCmp $UnArgOrigSid "" unLauncherNoSid
  StrCpy $3 '$3 /orig-sid $UnArgOrigSid'
unLauncherNoSid:
  StrCmp $UnArgOrigLocalAppData "" unLauncherNoLocal
  StrCpy $3 '$3 /orig-localappdata "$UnArgOrigLocalAppData"'
unLauncherNoLocal:
!ifdef FAF_TESTMODE
  StrCpy $3 '$3 ${FAF_QA_UI_EXTRA}'
  ; T20 runtime hook: /auto:mode=uninstall /auto:action=uninstall
  ; /auto:delete-user-data=... selected by the QA harness.
  ReadEnvStr $R4 "FAF_QA_UI_RUNTIME_EXTRA"
  StrCpy $3 '$3 $R4'
!endif
  ClearErrors
  Exec '$3'
  IfErrors unLauncherFailed
  Call un.WaitForRequest
  Goto unOnInitDone
unLauncherSilent:
  StrCpy $UnUiExpected "0"
  StrCpy $UnDeleteUserData "0"
  Call un.WriteStarted
  Goto unOnInitDone
unLauncherFailed:
  ; H3: failing to spawn the UI is NOT a failed uninstall. Nothing was deleted
  ; and no deletion started. WriteCancelled keeps stage=cancelled/done=1 and
  ; records warning=ui-launch-failed; WriteFailed would falsely claim stage=failed.
  ; A UI launch failure must still make the helper exit nonzero (2), so callers
  ; and QA cannot mistake it for success.
  StrCpy $UnWarning "ui-launch-failed"
  Call un.WriteCancelled
  ; SetErrorLevel does not reliably propagate through the uninstaller helper's
  ; Quit, so terminate the process with an explicit exit code instead.
  System::Call 'kernel32::ExitProcess(i 2)'

unHelper:
  ; UI wrote the request before spawning this helper. Never delete it; only a
  ; stale result is discarded.
  Delete "$UnResultIni"
  StrCpy $UnUiExpected "1"
  StrCpy $UnDeleteUserData "0"
  Call un.WriteStarted
  Call un.WaitForRequest
  Goto unOnInitDone

unOnInitDone:
FunctionEnd

Section "Install"
  ; T16: test builds must never create or delete any production key. The 32-bit
  ; orphan cleanup below is a production-only action; production writes go to the
  ; native 64-bit view.
!ifdef FAF_TESTMODE
  SetRegView 64
!else
  ; Upgrade orphan cleanup: an older installer may have left the Uninstall entry in
  ; the 32-bit view (Wow6432Node); remove that same-named entry first so an upgrade
  ; cannot produce a duplicate Add/Remove Programs item.
  SetRegView 32
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilter"
  SetRegView 64
!endif

  ; T16: install the uninstall stack (UI + MinGW runtime + NSIS helper) before any
  ; Add/Remove metadata is written. The UI/DLL are copied to temporary names first
  ; and renamed into place only after the complete copy is verified, so a partial
  ; file can never be referenced by UninstallString.
  CreateDirectory "$INSTDIR"
  Delete "$INSTDIR\FreeAssetFilterUninstall.exe.tmp"
  Delete "$INSTDIR\libwinpthread-1.dll.tmp"
  CopyFiles /SILENT "$PLUGINSDIR\FreeAssetFilterInstaller.exe" "$INSTDIR\FreeAssetFilterUninstall.exe.tmp"
  CopyFiles /SILENT "$PLUGINSDIR\libwinpthread-1.dll" "$INSTDIR\libwinpthread-1.dll.tmp"
  IfFileExists "$INSTDIR\FreeAssetFilterUninstall.exe.tmp" 0 uninstallPayloadFailed
  IfFileExists "$INSTDIR\libwinpthread-1.dll.tmp" 0 uninstallPayloadFailed

!ifdef FAF_TESTMODE
  ; T20/F1: deterministic UI-payload failure injection (test builds only;
  ; production compiles this block out). Proves that aborting here leaves no
  ; UninstallString/uninstall key and no uninstaller executable behind.
  ReadEnvStr $R2 "FAF_QA_FAIL_UI_COPY"
  StrCmp $R2 "1" 0 uiCopyCheckDone
  SetErrorLevel 2
  Goto uninstallPayloadFailed
uiCopyCheckDone:
!endif

  ; Rename does not overwrite here: retire the previous file as .old first, flip
  ; the verified temp into place, and restore .old if the final rename fails.
  Delete "$INSTDIR\libwinpthread-1.dll.old"
  Rename "$INSTDIR\libwinpthread-1.dll" "$INSTDIR\libwinpthread-1.dll.old"
  ClearErrors
  Rename "$INSTDIR\libwinpthread-1.dll.tmp" "$INSTDIR\libwinpthread-1.dll"
  IfErrors uninstallDllRenameFailed

  Delete "$INSTDIR\FreeAssetFilterUninstall.exe.old"
  Rename "$INSTDIR\FreeAssetFilterUninstall.exe" "$INSTDIR\FreeAssetFilterUninstall.exe.old"
  ClearErrors
  Rename "$INSTDIR\FreeAssetFilterUninstall.exe.tmp" "$INSTDIR\FreeAssetFilterUninstall.exe"
  IfErrors uninstallUiRenameFailed

  IfFileExists "$INSTDIR\FreeAssetFilterUninstall.exe" 0 uninstallPayloadFailed
  IfFileExists "$INSTDIR\libwinpthread-1.dll" 0 uninstallPayloadFailed

  ; WriteUninstaller failure is an install failure: verify the helper on disk and
  ; never fall through to writing UninstallString without it.
  ClearErrors
  WriteUninstaller "$INSTDIR\UninstallHelper.exe"
  IfErrors uninstallHelperFailed
  IfFileExists "$INSTDIR\UninstallHelper.exe" 0 uninstallHelperFailed

  ; UI + helper + DLL are all verified; only now remove the legacy single-file
  ; uninstaller and the retired backups.
  Delete "$INSTDIR\Uninstall.exe"
  Delete "$INSTDIR\FreeAssetFilterUninstall.exe.old"
  Delete "$INSTDIR\libwinpthread-1.dll.old"

  ; Optional desktop shortcut (flag from the result INI). A stale shortcut from an
  ; earlier install is removed when the flag is 0. Test builds use the isolated
  ; FreeAssetFilterTest.lnk and can never touch the production shortcut.
  ReadINIStr $0 "${RESULT_INI}" "install" "desktop"
  StrCmp $0 "1" 0 desktopRemove
  CreateShortcut "$DESKTOP\${SHORTCUT_STEM}.lnk" "$INSTDIR\FreeAssetFilter.exe"
  Goto desktopDone
desktopRemove:
  Delete "$DESKTOP\${SHORTCUT_STEM}.lnk"
desktopDone:
  ; Optional Start Menu shortcut. Production owns only its own FreeAssetFilter
  ; folder; test builds use a flat FreeAssetFilterTest.lnk and never create or
  ; remove a production folder.
  ReadINIStr $0 "${RESULT_INI}" "install" "startmenu"
  StrCmp $0 "1" 0 startmenuRemove
!ifdef FAF_TESTMODE
  CreateShortcut "$SMPROGRAMS\${SHORTCUT_STEM}.lnk" "$INSTDIR\FreeAssetFilter.exe"
!else
  CreateDirectory "$SMPROGRAMS\${SHORTCUT_STEM}"
  CreateShortcut "$SMPROGRAMS\${SHORTCUT_STEM}\${SHORTCUT_STEM}.lnk" "$INSTDIR\FreeAssetFilter.exe"
!endif
  Goto startmenuDone
startmenuRemove:
!ifdef FAF_TESTMODE
  Delete "$SMPROGRAMS\${SHORTCUT_STEM}.lnk"
!else
  Delete "$SMPROGRAMS\${SHORTCUT_STEM}\${SHORTCUT_STEM}.lnk"
  RMDir "$SMPROGRAMS\${SHORTCUT_STEM}"
!endif
startmenuDone:

  ; T16: install-info metadata. Test builds use the isolated per-user test key;
  ; production uses the production key.
!ifdef FAF_TESTMODE
  WriteRegStr HKCU "Software\FreeAssetFilterTest" "InstallDir" "$INSTDIR"
!else
  WriteRegStr HKCU "Software\FreeAssetFilter" "InstallDir" "$INSTDIR"
!endif

  ; Add/Remove Programs metadata. Production: native 64-bit HKLM view. Test: the
  ; same value names under the per-user HKCU test key; never a production key.
!ifdef FAF_TESTMODE
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilterTest" "DisplayName" "FreeAssetFilter"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilterTest" "UninstallString" '"$INSTDIR\UninstallHelper.exe" /uninstall-launcher /installdir "$INSTDIR" /ui "$INSTDIR\FreeAssetFilterUninstall.exe"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilterTest" "QuietUninstallString" '"$INSTDIR\UninstallHelper.exe" /S /installdir "$INSTDIR"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilterTest" "InstallLocation" "$INSTDIR"
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
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilter" "UninstallString" '"$INSTDIR\UninstallHelper.exe" /uninstall-launcher /installdir "$INSTDIR" /ui "$INSTDIR\FreeAssetFilterUninstall.exe"'
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilter" "QuietUninstallString" '"$INSTDIR\UninstallHelper.exe" /S /installdir "$INSTDIR"'
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilter" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilter" "DisplayIcon" '"$INSTDIR\FreeAssetFilter.exe"'
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilter" "DisplayVersion" "1.0.0-alpha.5"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilter" "Publisher" "Dorufoc & renmoren"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilter" "URLInfoAbout" "https://github.com/Dorufoc/FreeAssetFilter"
  ; EstimatedSize is a DWORD in KB (${GetSize} with /S=0K returns the total in KB in $0).
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilter" "EstimatedSize" $0
!endif

  ; Persisted option flags (D11): DWORDs written even when 0 so MaintenanceDetector
  ; never has to infer a disabled option. Normalize anything else to 0.
  ReadINIStr $4 "${RESULT_INI}" "install" "desktop"
  StrCmp $4 "1" optDesktopOn
  StrCpy $4 0
optDesktopOn:
  ReadINIStr $5 "${RESULT_INI}" "install" "startmenu"
  StrCmp $5 "1" optStartmenuOn
  StrCpy $5 0
optStartmenuOn:
  ReadINIStr $6 "${RESULT_INI}" "install" "autostart"
  StrCmp $6 "1" optAutostartOn
  StrCpy $6 0
optAutostartOn:
!ifdef FAF_TESTMODE
  WriteRegDWORD HKCU "Software\FreeAssetFilterTest" "OptDesktop" $4
  WriteRegDWORD HKCU "Software\FreeAssetFilterTest" "OptStartmenu" $5
  WriteRegDWORD HKCU "Software\FreeAssetFilterTest" "OptAutostart" $6
!else
  WriteRegDWORD HKCU "Software\FreeAssetFilter" "OptDesktop" $4
  WriteRegDWORD HKCU "Software\FreeAssetFilter" "OptStartmenu" $5
  WriteRegDWORD HKCU "Software\FreeAssetFilter" "OptAutostart" $6
!endif

  ; Optional autostart Run value (production only). Test builds must never read,
  ; write, or delete the production Run value; OptAutostart is still persisted in
  ; the isolated test install-info key above.
!ifdef FAF_TESTMODE
  ; Intentionally no Run side effect in test builds.
!else
  ; When disabled, delete only a value that is OURS (quote-consistent compare) -
  ; a value pointing elsewhere is never touched.
  StrCmp $6 "1" 0 autostartOff
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "FreeAssetFilter" '"$INSTDIR\FreeAssetFilter.exe"'
  Goto autostartDone
autostartOff:
  ReadRegStr $1 HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "FreeAssetFilter"
  StrCmp $1 '"$INSTDIR\FreeAssetFilter.exe"' 0 autostartDone
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "FreeAssetFilter"
autostartDone:
!endif

  ; Successful install: the maintenance handoff file has served its purpose.
  Delete "$INSTDIR\maintenance-decision.ini"
  Goto installDone

uninstallDllRenameFailed:
  Rename "$INSTDIR\libwinpthread-1.dll.old" "$INSTDIR\libwinpthread-1.dll"
  Goto uninstallPayloadFailed
uninstallUiRenameFailed:
  Rename "$INSTDIR\FreeAssetFilterUninstall.exe.old" "$INSTDIR\FreeAssetFilterUninstall.exe"
  Goto uninstallPayloadFailed
uninstallHelperFailed:
  Delete "$INSTDIR\FreeAssetFilterUninstall.exe.old"
  Delete "$INSTDIR\libwinpthread-1.dll.old"
  Abort
uninstallPayloadFailed:
  Delete "$INSTDIR\FreeAssetFilterUninstall.exe.tmp"
  Delete "$INSTDIR\libwinpthread-1.dll.tmp"
  Abort
installDone:
SectionEnd

Section "Uninstall"
  ; Defensive fallback for a Section reached without un.onInit (not expected).
  StrCmp $UnResultIni "" 0 unSecPathsReady
  StrCpy $UnRequestIni "$INSTDIR\${UNINSTALL_REQUEST_FILE}"
  StrCpy $UnResultIni "$INSTDIR\${UNINSTALL_RESULT_FILE}"
  StrCpy $UnUiExe "$INSTDIR\FreeAssetFilterUninstall.exe"
unSecPathsReady:

  ; ---- Stage 1: shortcuts -------------------------------------------------
  StrCpy $0 "removing_shortcuts"
  StrCpy $1 "100"
  Call un.WriteProgress
  Delete "$DESKTOP\${SHORTCUT_STEM}.lnk"
  IfFileExists "$DESKTOP\${SHORTCUT_STEM}.lnk" 0 unSecDesktopDone
  StrCpy $UnErrorText "$DESKTOP\${SHORTCUT_STEM}.lnk"
  Goto unSecFail
unSecDesktopDone:
!ifdef FAF_TESTMODE
  Delete "$SMPROGRAMS\${SHORTCUT_STEM}.lnk"
  IfFileExists "$SMPROGRAMS\${SHORTCUT_STEM}.lnk" 0 unSecStartDone
  StrCpy $UnErrorText "$SMPROGRAMS\${SHORTCUT_STEM}.lnk"
  Goto unSecFail
!else
  Delete "$SMPROGRAMS\${SHORTCUT_STEM}\${SHORTCUT_STEM}.lnk"
  IfFileExists "$SMPROGRAMS\${SHORTCUT_STEM}\${SHORTCUT_STEM}.lnk" 0 unSecStartDone
  StrCpy $UnErrorText "$SMPROGRAMS\${SHORTCUT_STEM}\${SHORTCUT_STEM}.lnk"
  Goto unSecFail
!endif
unSecStartDone:
!ifndef FAF_TESTMODE
  ; A folder containing unrelated user files is left alone; it is not an error.
  RMDir "$SMPROGRAMS\${SHORTCUT_STEM}"
!endif

  ; ---- Stage 2: registry --------------------------------------------------
  StrCpy $0 "removing_registry"
  StrCpy $1 "300"
  Call un.WriteProgress
  SetRegView 64
!ifndef FAF_TESTMODE
  ; Run value: remove only the quote-consistent value written by Section Install.
  ReadRegStr $2 HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "FreeAssetFilter"
  StrCmp $2 '"$INSTDIR\FreeAssetFilter.exe"' 0 unSecRunDone
  ClearErrors
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "FreeAssetFilter"
  IfErrors unSecRunFail
  Goto unSecRunDone
unSecRunFail:
  StrCpy $UnErrorText "HKCU\Software\Microsoft\Windows\CurrentVersion\Run\FreeAssetFilter"
  Goto unSecFail
unSecRunDone:
!endif

  ; Add/Remove entry, native 64-bit view (production HKLM; test HKCU test key).
!ifdef FAF_TESTMODE
  ReadRegStr $2 HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilterTest" "DisplayName"
  StrCmp $2 "" unSecUninst64Done
  ClearErrors
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilterTest"
  IfErrors unSecUninst64Fail
  Goto unSecUninst64Done
unSecUninst64Fail:
  StrCpy $UnErrorText "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilterTest"
  Goto unSecFail
unSecUninst64Done:
!else
  ReadRegStr $2 HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilter" "DisplayName"
  StrCmp $2 "" unSecUninst64Done
  ClearErrors
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilter"
  IfErrors unSecUninst64Fail
  Goto unSecUninst64Done
unSecUninst64Fail:
  StrCpy $UnErrorText "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilter"
  Goto unSecFail
unSecUninst64Done:
!endif

  ; Install-info key (InstallDir/Opt*); InstallLocation lives on the uninstall key.
!ifdef FAF_TESTMODE
  ReadRegStr $2 HKCU "Software\FreeAssetFilterTest" "InstallDir"
  StrCmp $2 "" unSecInfoDone
  ClearErrors
  DeleteRegKey HKCU "Software\FreeAssetFilterTest"
  IfErrors unSecInfoFail
  Goto unSecInfoDone
unSecInfoFail:
  StrCpy $UnErrorText "HKCU\Software\FreeAssetFilterTest"
  Goto unSecFail
unSecInfoDone:
!else
  ReadRegStr $2 HKCU "Software\FreeAssetFilter" "InstallDir"
  StrCmp $2 "" unSecInfoDone
  ClearErrors
  DeleteRegKey HKCU "Software\FreeAssetFilter"
  IfErrors unSecInfoFail
  Goto unSecInfoDone
unSecInfoFail:
  StrCpy $UnErrorText "HKCU\Software\FreeAssetFilter"
  Goto unSecFail
unSecInfoDone:
!endif

  ; Legacy 32-bit HKLM view. HKCU is not WOW64-redirected; for test builds this
  ; repeats the same idempotent test-key deletion and normally finds nothing.
  SetRegView 32
!ifdef FAF_TESTMODE
  ReadRegStr $2 HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilterTest" "DisplayName"
  StrCmp $2 "" unSecUninst32Done
  ClearErrors
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilterTest"
  IfErrors unSecUninst32Fail
  Goto unSecUninst32Done
unSecUninst32Fail:
  StrCpy $UnErrorText "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilterTest"
  Goto unSecFail
unSecUninst32Done:
!else
  ReadRegStr $2 HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilter" "DisplayName"
  StrCmp $2 "" unSecUninst32Done
  ClearErrors
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilter"
  IfErrors unSecUninst32Fail
  Goto unSecUninst32Done
unSecUninst32Fail:
  StrCpy $UnErrorText "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\FreeAssetFilter"
  Goto unSecFail
unSecUninst32Done:
!endif
  SetRegView 64

  ; ---- Stage 3: files -----------------------------------------------------
  StrCpy $0 "removing_files"
  StrCpy $1 "500"
  Call un.WriteProgress

  ; _internal app files, preserving only _internal\data (handled by stage 4).
  StrCpy $R5 "$INSTDIR\_internal"
  StrCpy $R6 "data"
  StrCpy $R8 "0"
  IfFileExists "$R5" 0 unSecInternalDone
  Call un.DeleteTree
  StrCmp $UnFailedPath "" 0 unSecPathFail
unSecInternalDone:

  IfFileExists "$INSTDIR\FreeAssetFilter.exe" 0 unSecAppDone
  Delete "$INSTDIR\FreeAssetFilter.exe"
  IfFileExists "$INSTDIR\FreeAssetFilter.exe" 0 unSecAppDone
  StrCpy $UnErrorText "$INSTDIR\FreeAssetFilter.exe"
  Goto unSecFail
unSecAppDone:

  IfFileExists "$INSTDIR\Uninstall.exe" 0 unSecLegacyDone
  Delete "$INSTDIR\Uninstall.exe"
  IfFileExists "$INSTDIR\Uninstall.exe" 0 unSecLegacyDone
  StrCpy $UnErrorText "$INSTDIR\Uninstall.exe"
  Goto unSecFail
unSecLegacyDone:

  ; Retired install-stack leftovers are app-owned; report the exact leftover.
  Delete "$INSTDIR\FreeAssetFilterUninstall.exe.old"
  IfFileExists "$INSTDIR\FreeAssetFilterUninstall.exe.old" 0 unSecTempUiOldDone
  StrCpy $UnErrorText "$INSTDIR\FreeAssetFilterUninstall.exe.old"
  Goto unSecFail
unSecTempUiOldDone:
  Delete "$INSTDIR\libwinpthread-1.dll.old"
  IfFileExists "$INSTDIR\libwinpthread-1.dll.old" 0 unSecTempDllOldDone
  StrCpy $UnErrorText "$INSTDIR\libwinpthread-1.dll.old"
  Goto unSecFail
unSecTempDllOldDone:
  Delete "$INSTDIR\FreeAssetFilterUninstall.exe.tmp"
  IfFileExists "$INSTDIR\FreeAssetFilterUninstall.exe.tmp" 0 unSecTempUiTmpDone
  StrCpy $UnErrorText "$INSTDIR\FreeAssetFilterUninstall.exe.tmp"
  Goto unSecFail
unSecTempUiTmpDone:
  Delete "$INSTDIR\libwinpthread-1.dll.tmp"
  IfFileExists "$INSTDIR\libwinpthread-1.dll.tmp" 0 unSecTempDllTmpDone
  StrCpy $UnErrorText "$INSTDIR\libwinpthread-1.dll.tmp"
  Goto unSecFail
unSecTempDllTmpDone:
  Goto unSecUserData

  ; ---- Stage 4: user data -------------------------------------------------
unSecUserData:
  StrCpy $0 "removing_user_data"
  StrCpy $1 "800"
  Call un.WriteProgress
  StrCmp $UnDeleteUserData "1" 0 unSecFinishing

  ReadEnvStr $UnFafDataDir "FAF_DATA_DIR"
  StrCpy $R5 $UnFafDataDir
  Call un.StripTrailingSlash
  StrCpy $UnFafDataDir $R5

  ; Canonical per-user data root (test build has its own root).
  StrCpy $UnTarget "${UNINSTALL_DATA_ROOT}"
  StrCpy $R5 $UnTarget
  Call un.StripTrailingSlash
  StrCpy $UnTarget $R5
  StrCmp $UnFafDataDir "" unSecCanonicalGo
  StrCpy $R5 $UnTarget
  StrCpy $R6 $UnFafDataDir
  Call un.PathsOverlap
  StrCmp $R7 1 0 unSecCanonicalGo
  StrCpy $0 "user-data-custom-overlap"
  Call un.AddWarning
  Goto unSecCanonicalDone
unSecCanonicalGo:
  IfFileExists "$UnTarget" 0 unSecCanonicalDone
  StrCpy $R5 $UnTarget
  StrCpy $R6 ""
  StrCpy $R8 "1"
  Call un.DeleteTree
  StrCmp $UnFailedPath "" 0 unSecPathFail
unSecCanonicalDone:

  ; Portable/legacy data under the install directory.
  StrCpy $UnTarget "$INSTDIR\data"
  StrCpy $R5 $UnTarget
  Call un.StripTrailingSlash
  StrCpy $UnTarget $R5
  StrCmp $UnFafDataDir "" unSecInstallDataGo
  StrCpy $R5 $UnTarget
  StrCpy $R6 $UnFafDataDir
  Call un.PathsOverlap
  StrCmp $R7 1 0 unSecInstallDataGo
  StrCpy $0 "user-data-custom-overlap"
  Call un.AddWarning
  Goto unSecInstallDataDone
unSecInstallDataGo:
  IfFileExists "$UnTarget" 0 unSecInstallDataDone
  StrCpy $R5 $UnTarget
  StrCpy $R6 ""
  StrCpy $R8 "1"
  Call un.DeleteTree
  StrCmp $UnFailedPath "" 0 unSecPathFail
unSecInstallDataDone:

  StrCpy $UnTarget "$INSTDIR\_internal\data"
  StrCpy $R5 $UnTarget
  Call un.StripTrailingSlash
  StrCpy $UnTarget $R5
  StrCmp $UnFafDataDir "" unSecInternalDataGo
  StrCpy $R5 $UnTarget
  StrCpy $R6 $UnFafDataDir
  Call un.PathsOverlap
  StrCmp $R7 1 0 unSecInternalDataGo
  StrCpy $0 "user-data-custom-overlap"
  Call un.AddWarning
  Goto unSecInternalDataDone
unSecInternalDataGo:
  IfFileExists "$UnTarget" 0 unSecInternalDataDone
  StrCpy $R5 $UnTarget
  StrCpy $R6 ""
  StrCpy $R8 "1"
  Call un.DeleteTree
  StrCmp $UnFailedPath "" 0 unSecPathFail
unSecInternalDataDone:

  ; ---- Stage 5: finishing -------------------------------------------------
unSecFinishing:
  ; done=1 MUST be observable before the UI is asked to close (plan line 1084).
  StrCpy $0 "done"
  StrCpy $1 "1000"
  Call un.WriteProgress
  Call un.WriteDone

  StrCmp $UnUiExpected "1" 0 unSecDeleteTerminal
  StrCpy $0 0
unSecUiWaitLoop:
  IfFileExists "$UnRequestIni" 0 unSecUiProc
  ReadINIStr $1 "$UnRequestIni" "${UNINSTALL_SECTION}" "ui_done"
  StrCmp $1 "1" unSecUiDone
unSecUiProc:
  StrCmp $UnUiProcess 0 unSecUiFind
  System::Call 'kernel32::WaitForSingleObject(p $UnUiProcess, i 0) i .r1'
  StrCmp $1 0 unSecDeleteTerminal
  Goto unSecUiTick
unSecUiFind:
  FindWindow $R0 "FreeAssetFilterInstaller" ""
  StrCmp $R0 0 unSecDeleteTerminal
unSecUiTick:
  Sleep ${FAF_UNINSTALL_POLL_MS}
  IntOp $0 $0 + ${FAF_UNINSTALL_POLL_MS}
  IntCmp $0 ${FAF_UNINSTALL_UI_DONE_TIMEOUT_MS} 0 0 unSecUiTimeout
  Goto unSecUiWaitLoop
unSecUiDone:
  StrCmp $UnUiProcess 0 unSecUiDoneFind
  System::Call 'kernel32::WaitForSingleObject(p $UnUiProcess, i ${FAF_UNINSTALL_UI_PROCESS_WAIT_MS}) i .r1'
  StrCmp $1 0 unSecDeleteTerminal
  Goto unSecUiTimeout
unSecUiDoneFind:
  StrCpy $0 0
unSecUiDoneFindLoop:
  FindWindow $R0 "FreeAssetFilterInstaller" ""
  StrCmp $R0 0 unSecDeleteTerminal
  Sleep ${FAF_UNINSTALL_POLL_MS}
  IntOp $0 $0 + ${FAF_UNINSTALL_POLL_MS}
  IntCmp $0 ${FAF_UNINSTALL_UI_PROCESS_WAIT_MS} 0 0 unSecUiTimeout
  Goto unSecUiDoneFindLoop

unSecUiTimeout:
  ; M2: UI did not exit. Keep the UI/DLL/helper and the result; do not remove
  ; anything after done=1.
  StrCpy $0 "ui-timeout"
  Call un.AddWarning
  WriteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "warning" "$UnWarning"
  Call un.FlushResult
  StrCmp $UnUiProcess 0 unSecUiTimeoutQuit
  System::Call 'kernel32::CloseHandle(p $UnUiProcess)'
  StrCpy $UnUiProcess 0
unSecUiTimeoutQuit:
  Quit

unSecDeleteTerminal:
  StrCmp $UnUiProcess 0 unSecNoProcessClose
  System::Call 'kernel32::CloseHandle(p $UnUiProcess)'
  StrCpy $UnUiProcess 0
unSecNoProcessClose:
  ; M1: UI exit is confirmed; it may have run from a setup-owned temp copy.
  ; Remove only the exact maintenance temp directory (UI self-clean may already
  ; have removed it). Never touches $INSTDIR, $PLUGINSDIR or other paths.
  Call un.CleanupUiTempDir

  ; UI and its MinGW runtime may now be deleted. Delete /REBOOTOK failure is a
  ; post-done warning, never stage=failed.
  IfFileExists "$UnUiExe" 0 unSecUiGone
  ClearErrors
  Delete /REBOOTOK "$UnUiExe"
  IfFileExists "$UnUiExe" 0 unSecUiGone
  StrCpy $0 "reboot_pending"
  Call un.AddWarning
unSecUiGone:

  IfFileExists "$INSTDIR\libwinpthread-1.dll" 0 unSecDllGone
  ClearErrors
  Delete /REBOOTOK "$INSTDIR\libwinpthread-1.dll"
  IfFileExists "$INSTDIR\libwinpthread-1.dll" 0 unSecDllGone
  StrCpy $0 "reboot_pending"
  Call un.AddWarning
unSecDllGone:


  ; Persist post-done warnings; done remains 1.
  StrCmp $UnWarning "" unSecClearWarning
  WriteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "warning" "$UnWarning"
  Goto unSecWarningWritten
unSecClearWarning:
  DeleteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "warning"
unSecWarningWritten:
  Call un.FlushResult

  ; Request/result are only removed after done=1 and UI exit.
  Delete "$UnRequestIni"
  Delete "$UnResultIni"
  RMDir "$INSTDIR\_internal"
  RMDir "$INSTDIR"
  IfFileExists "$INSTDIR" 0 unSecComplete

  ; Preserved user data keeps the install dir non-empty. Recreate a terminal
  ; result with the warning so the condition remains observable.
  StrCpy $0 "install-dir-not-empty"
  Call un.AddWarning
  WriteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "schema" "1"
  WriteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "stage" "done"
  WriteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "permille" "1000"
  WriteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "warning" "$UnWarning"
  WriteINIStr "$UnResultIni" "${UNINSTALL_SECTION}" "done" "1"
  Call un.FlushResult
unSecComplete:
  Quit

unSecPathFail:
  StrCpy $UnErrorText "$UnFailedPath"
unSecFail:
  Call un.WriteFailed
  Quit
SectionEnd
