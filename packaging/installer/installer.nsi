Unicode true
; Prioritize smallest installer size over build/extraction speed.
; Keep bootstrap files independently extractable so the GUI appears immediately.
; Section Install writes the shortcuts, the autostart Run value, the Explorer
; context-menu verbs (ctxmenu=1 -> *\shell\SopeekOpenFile plus
; Directory\shell\SopeekOpenFolder and Directory\Background\shell\SopeekOpenFolder,
; served by the in-proc IExplorerCommand handler in SopeekShellExt.dll) and the
; Add/Remove metadata; Section Uninstall removes each of them again.
; Keep this file UTF-8 with BOM: the context-menu labels are Chinese and makensis
; reads a BOM-less script as ACP, which it rejects as bad text encoding.
SetCompressor lzma
SetCompressorDictSize 64
!include LogicLib.nsh
!include FileFunc.nsh
; Test-build isolation scaffolding. The test-mode macro checked here is a makensis
; command-line define; the production build never passes it and therefore always
; takes the `!else` branch below (unchanged behavior).
!ifdef SPK_TESTMODE
RequestExecutionLevel user
!else
RequestExecutionLevel admin
!endif
ManifestDPIAware true
Name "Sopeek Installer"
; Output override: build.ps1 always passes -DSPK_OUTFILE=..\..\build\Sopeek-<version>-<platform>-<arch>-<timestamp>.exe
; (e.g. Sopeek-2.0.0-windows-x64-261118153045.exe) so the packaged file name carries
; product, version, target platform/arch and build time. The fallback below keeps a
; bare `makensis installer.nsi` invocation, and QA builds pass their own isolated path.
!ifndef SPK_OUTFILE
  !define SPK_OUTFILE "..\..\build\Sopeek_NSIS_Setup.exe"
!endif
OutFile "${SPK_OUTFILE}"
; Test build installs into the per-user profile (no elevation needed); the
; production build keeps the machine-wide Program Files default (unchanged).
!ifdef SPK_TESTMODE
InstallDir "$LOCALAPPDATA\SopeekTest"
!else
InstallDir "$PROGRAMFILES64\Sopeek"
!endif
; T15: the installed-detection source is the same key Section Install writes.
; The test build uses the isolated HKCU test key (never the production one).
!ifdef SPK_TESTMODE
  InstallDirRegKey HKCU "Software\SopeekTest" "InstallDir"
!else
  InstallDirRegKey HKCU "Software\Sopeek" "InstallDir"
!endif
SilentInstall silent
SilentUninstall silent
ShowInstDetails nevershow
; Setup / uninstaller icon: project icon (SPK-setup.ico) instead of the default NSIS icon.
Icon "..\..\src\sopeek\resources\icons\SPK-setup.ico"
UninstallIcon "..\..\src\sopeek\resources\icons\SPK-setup.ico"
; Version metadata is derived from SPKVERSION by build.ps1 and passed in with -D, so a
; nightly build reports its own version instead of a frozen literal. The !ifndef
; fallbacks keep a bare `makensis installer.nsi` (and the test-build pipeline) working.
!ifndef SPK_PRODUCT_VERSION
  !define SPK_PRODUCT_VERSION "0.0.0"
!endif
; VIProductVersion must be four dot-separated integers in 0..65535.
!ifndef SPK_PRODUCT_VERSION_NUMERIC
  !define SPK_PRODUCT_VERSION_NUMERIC "0.0.0.0"
!endif
!ifndef SPK_FILE_VERSION
  !define SPK_FILE_VERSION "${SPK_PRODUCT_VERSION}"
!endif
VIProductVersion "${SPK_PRODUCT_VERSION_NUMERIC}"
VIAddVersionKey /LANG=1033 "ProductName" "Sopeek"
VIAddVersionKey /LANG=1033 "FileDescription" "Sopeek"
VIAddVersionKey /LANG=1033 "FileVersion" "${SPK_FILE_VERSION}"
VIAddVersionKey /LANG=1033 "ProductVersion" "${SPK_PRODUCT_VERSION}"
VIAddVersionKey /LANG=1033 "CompanyName" "Dorufoc & renmoren"
VIAddVersionKey /LANG=1033 "LegalCopyright" "Copyright (c) 2026 Dorufoc & renmoren"

!define APP "Sopeek.exe"
!define PAYLOAD "..\..\build\pyinstall\Sopeek"

; ── Explorer 右键菜单（in-proc COM 扩展）────────────────────────────────────
; 两个独立命令，由随 payload 安装的 SopeekShellExt.dll（IExplorerCommand）
; 提供，Windows 10 经典菜单与 Windows 11 现代菜单共用同一份注册：
;   * "用Sopeek软件打开"   —— 任意文件（不注册任何后缀关联）
;   * "使用Sopeek打开"     —— 文件夹图标与文件夹空白处
; 生产与测试各用一对 CLSID：测试构建只写 HKCU，同一个 CLSID 在用户级注册会
; 遮蔽 HKLM 的生产注册，因此测试绝不能复用生产 GUID。
!define SPK_SHELLEXT_DLL "SopeekShellExt.dll"
!ifdef SPK_TESTMODE
  !define SPK_CTX_ROOT "HKCU"
  !define SPK_CTX_FILE_CLSID "{ADD20484-57FF-4DEB-8561-AC7F04CAFDCB}"
  !define SPK_CTX_FOLDER_CLSID "{430F8D9E-4290-46F8-8E40-E38DAB04C5BD}"
  !define SPK_CTX_FILE_VERB "SopeekOpenFileTest"
  !define SPK_CTX_FOLDER_VERB "SopeekOpenFolderTest"
  !define SPK_CTX_LEGACY_VERB "SopeekTest"
!else
  !define SPK_CTX_ROOT "HKLM"
  !define SPK_CTX_FILE_CLSID "{02F1BD14-A1B5-4B9E-9E10-C756D537FDA0}"
  !define SPK_CTX_FOLDER_CLSID "{39F01A4C-DD1D-48D2-8FB3-0E0C76B336BC}"
  !define SPK_CTX_FILE_VERB "SopeekOpenFile"
  !define SPK_CTX_FOLDER_VERB "SopeekOpenFolder"
  !define SPK_CTX_LEGACY_VERB "Sopeek"
!endif
; Exact payload size in bytes, measured by build.ps1 before packaging and forwarded
; to the GUI. 0 means "unknown" (e.g. a test/QA build that omits the define) and the
; GUI falls back to scanning the payload directory itself.
!ifndef PAYLOAD_BYTES
  !define PAYLOAD_BYTES 0
!endif
; Result protocol: the GUI install engine is the ONLY writer of this INI; NSIS is a
; pure reader. Only the terminal `abort` key (written last by the GUI) means
; "finished" - file existence alone is never used as the readiness signal.
!define RESULT_INI "$PLUGINSDIR\install-result.ini"
; Bounded wait for the terminal key. Production default 30 min, strictly greater
; than the GUI's own payload-wait default of 25 min (so the GUI never keeps waiting
; on a dead NSIS process). QA override: makensis -DSPK_WAIT_TIMEOUT_MS=60000 installer.nsi
!ifndef SPK_WAIT_TIMEOUT_MS
  !define SPK_WAIT_TIMEOUT_MS 1800000
!endif
; H5: bounded wait for the GUI's FIRST visible window. Together with the Exec
; error check this turns "process started but never produced a UI" into a fast,
; nonzero failure instead of a 30-minute silent wait. Seen-window liveness keeps
; the existing 3s grace and total timeout.
!ifndef SPK_GUI_WINDOW_DETECT_MS
  !define SPK_GUI_WINDOW_DETECT_MS 10000
!endif

; T15 maintenance handoff. Strings mirror src/render/maintenance_protocol.h; NSIS
; cannot include the C++ header. Mutexes are per-session Local\ objects. The test
; build gets its own names so it can never collide with a real setup / real UI.
!ifdef SPK_TESTMODE
  !define SETUP_MUTEX "Local\SopeekSetupMutex.Test"
  !define MAINTENANCE_MUTEX "Local\SopeekMaintenanceMutex.Test"
!else
  !define SETUP_MUTEX "Local\SopeekSetupMutex"
  !define MAINTENANCE_MUTEX "Local\SopeekMaintenanceMutex"
!endif

; D13/F2 shortcut isolation (mirrors maintenance_protocol.h::kShortcutStem*).
; Production: desktop Sopeek.lnk + Start Menu folder
; Sopeek\Sopeek.lnk. Test: flat SopeekTest.lnk on both
; desktop and Start Menu; it must never create/delete/overwrite a production
; shortcut (including the legacy flat production Start Menu file).
!define SHORTCUT_STEM_PROD "Sopeek"
!ifdef SPK_TESTMODE
  !define SHORTCUT_STEM_TEST "SopeekTest"
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
!ifndef SPK_DECISION_TIMEOUT_MS
  !define SPK_DECISION_TIMEOUT_MS 1800000
!endif

; Automated test drive profile (contract §17): four 0/1 chars =
; desktop/startmenu/autostart/launch, forwarded to the test GUI as
; `/auto:opts=<bits>` (see the test Exec in .onInit). QA overrides it on the
; makensis command line (-DSPK_AUTO_PROFILE=1101); the !ifndef fallback keeps a
; plain `makensis -DSPK_TESTMODE installer.nsi` build compiling and runnable.
!ifdef SPK_TESTMODE
  !ifndef SPK_AUTO_PROFILE
    !define SPK_AUTO_PROFILE "1101"
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
!ifdef SPK_TESTMODE
  !define UNINSTALL_ENGINE_MUTEX "Local\SopeekUninstallEngineMutex.Test"
  !define UNINSTALL_DATA_ROOT "$LOCALAPPDATA\SopeekTestUserData"
!else
  !define UNINSTALL_ENGINE_MUTEX "Local\SopeekUninstallEngineMutex"
  !define UNINSTALL_DATA_ROOT "$LOCALAPPDATA\Sopeek"
!endif
!define UNINSTALL_SECTION "uninstall"
!define UNINSTALL_REQUEST_FILE "uninstall-request.ini"
!define UNINSTALL_RESULT_FILE "uninstall-result.ini"
; Production defaults match maintenance_protocol.h. QA may override any of these
; on the makensis command line (for example a 6s request timeout to exercise the
; launcher cancellation path without waiting 30 minutes).
!ifndef SPK_UNINSTALL_REQUEST_TIMEOUT_MS
  !define SPK_UNINSTALL_REQUEST_TIMEOUT_MS 1800000
!endif
!ifndef SPK_UNINSTALL_UI_DONE_TIMEOUT_MS
  !define SPK_UNINSTALL_UI_DONE_TIMEOUT_MS 60000
!endif
!ifndef SPK_UNINSTALL_UI_PROCESS_WAIT_MS
  !define SPK_UNINSTALL_UI_PROCESS_WAIT_MS 10000
!endif
!ifndef SPK_UNINSTALL_SETUP_MUTEX_WAIT_MS
  !define SPK_UNINSTALL_SETUP_MUTEX_WAIT_MS 15000
!endif
!ifndef SPK_UNINSTALL_POLL_MS
  !define SPK_UNINSTALL_POLL_MS 200
!endif
; QA-only extra arguments appended to the UI command line by the launcher path.
; Empty in every normal test build; a QA build may pass e.g.
; -DSPK_QA_UI_EXTRA="/auto:page=6 /auto:action=uninstall". Never defined for
; production. T20 also reads SPK_QA_UI_RUNTIME_EXTRA at launch time so one test
; setup can exercise both delete_user_data=0 and =1 without rebuilding.
!ifdef SPK_TESTMODE
  !ifndef SPK_QA_UI_EXTRA
    !define SPK_QA_UI_EXTRA ""
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
Var /GLOBAL UnSpkDataDir

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
  FindWindow $1 "SopeekInstaller" ""
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
; $TEMP\SopeekMaintenance-<digits> directories are considered:
; non-directories, reparse points and paths younger than 24h are skipped.
; Age is an exact 64-bit FILETIME comparison, not a calendar-day check.
Function SweepStaleGuiCopies
  ClearErrors
  FindFirst $9 $8 "$TEMP\SopeekMaintenance-*"
  StrCmp $9 0 sweepDone
sweepLoop:
  StrCmp $8 "" sweepClose
  ; Leaf must be exactly the prefix followed by one or more ASCII digits.
  StrCpy $7 $8 18
  StrCmp $7 "SopeekMaintenance-" 0 sweepNext
  StrCpy $7 $8 "" 18
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
  StrCpy $GuiTempDir "$TEMP\SopeekMaintenance-$SetupPid"
  CreateDirectory "$GuiTempDir"
  CopyFiles /SILENT "$PLUGINSDIR\SopeekInstaller.exe" "$GuiTempDir"
  CopyFiles /SILENT "$PLUGINSDIR\libwinpthread-1.dll" "$GuiTempDir"
  StrCpy $GuiTempExe "$GuiTempDir\SopeekInstaller.exe"
  IfFileExists "$GuiTempExe" 0 guiCopyFailed
  IfFileExists "$GuiTempDir\libwinpthread-1.dll" 0 guiCopyFailed
  Return
guiCopyFailed:
  ; Never launch a GUI that cannot load its MinGW runtime.
  SetErrorLevel 2
  Call CloseSetupMutex
  Abort
FunctionEnd

; Shell-extension upgrade helper (called before the install engine copies the
; payload): a previously installed SopeekShellExt.dll may still be mapped into a
; running explorer.exe. A mapped image cannot be overwritten, so CopyFileExW
; would fail with a sharing violation and the whole install would abort with
; "copy-failed: SopeekShellExt.dll" (install_engine.cpp). Such an image can be
; renamed, so park it under .old and let the engine write a fresh file. The old
; copy is deleted immediately when nothing holds it; /REBOOTOK covers the case
; where explorer.exe still has it loaded. Uninstall Stage 3 already sweeps
; *.old/*.tmp leftovers.
Function ParkStaleShellExt
  StrCpy $R9 "0"  ; 0 = 旧扩展没被占用，新 DLL 直接生效；1 = 仍被 explorer 映射
  IfFileExists "$INSTDIR\${SPK_SHELLEXT_DLL}" 0 parkShellExtDone
  Delete "$INSTDIR\${SPK_SHELLEXT_DLL}.old"
  ClearErrors
  Rename "$INSTDIR\${SPK_SHELLEXT_DLL}" "$INSTDIR\${SPK_SHELLEXT_DLL}.old"
  IfErrors parkShellExtDone
  ClearErrors
  Delete "$INSTDIR\${SPK_SHELLEXT_DLL}.old"
  IfFileExists "$INSTDIR\${SPK_SHELLEXT_DLL}.old" 0 parkShellExtDone
  ; 改名成功但删不掉 ⇒ 旧的 shell 扩展 DLL 仍被某个 explorer.exe 映射。
  ; 这种情况下 explorer 的类工厂缓存里还留着旧对象，光换文件不会生效：
  ; 记下标记，注册完成后由 RestartExplorerForShellExt 处理。
  StrCpy $R9 "1"
  Delete /REBOOTOK "$INSTDIR\${SPK_SHELLEXT_DLL}.old"
parkShellExtDone:
FunctionEnd

; Windows 11 modern context menu (production only).
;
; The modern top-level menu only enumerates commands declared by an application
; that carries package identity; the plain ExplorerCommandHandler registry verbs
; register above therefore land in "Show more options" only. The payload ships a
; sparse package (SopeekShellMenu.msix) whose manifest declares the same two
; CLSIDs for * / Directory / Directory\Background, and register.ps1 trusts the
; signing certificate and registers the package against $INSTDIR through
; Add-AppxPackage -ExternalLocation.
;
; Failure is a warning, never an install abort: the classic menu still works and a
; policy-locked machine (sideloading disabled) must still be able to install.
; Production-only: test builds never reference it (HKCU isolation, no elevation),
; and an unreferenced Function would trip makensis warning 6010 under /WX.
!ifndef SPK_TESTMODE
Function RegisterShellMenuPackage
  ; 稀疏包 + windows.fileExplorerContextMenus 只有 Windows 11（build 22000+）才支持。
  ; Windows 10 上注册这个包不会产生任何现代菜单项，却会让开始菜单多出一个
  ; 与经典快捷方式重名的入口，所以直接跳过（此时只剩注册表动词 → 经典菜单）。
  ReadRegStr $R7 HKLM "SOFTWARE\Microsoft\Windows NT\CurrentVersion" CurrentBuildNumber
  IntOp $R7 $R7 + 0
  IntCmpU $R7 22000 0 shellMenuSkipOs 0
  IfFileExists "$INSTDIR\SopeekShellMenu.msix" 0 shellMenuMissing
  IfFileExists "$INSTDIR\shell_menu_register.ps1" 0 shellMenuMissing
  DetailPrint "Registering shell menu package"
  nsExec::ExecToStack '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$INSTDIR\shell_menu_register.ps1" -InstallDir "$INSTDIR"'
  Pop $1
  Pop $2
  StrCmp $1 "0" 0 shellMenuFailed
  DetailPrint "Shell menu package registered"
  ; 新版菜单的清单注册由 Explorer 在启动时读入（以及按 CLSID 缓存命令对象），
  ; 所以注册成功后同样需要重启 Explorer 才能看到新条目：与「旧 DLL 被映射」
  ; 共用同一个重启流程，避免用户装完却看不到任何新菜单。
  StrCpy $R9 "1"
  ; Diagnostic breadcrumb: silent installs have no UI to read DetailPrint from, and
  ; the modern-menu feature is the one part that can be blocked by machine policy.
  FileOpen $3 "$INSTDIR\shell_menu_status.txt" w
  FileWrite $3 "status=ok$\r$\n"
  FileClose $3
  Goto shellMenuDone
shellMenuFailed:
  DetailPrint "Shell menu package registration failed (exit=$1): $2"
  FileOpen $3 "$INSTDIR\shell_menu_status.txt" w
  FileWrite $3 "status=failed$\r$\nexit=$1$\r$\n$2$\r$\n"
  FileClose $3
  ; The modern menu is the one feature machine policy can silently block, and a
  ; user who ticked 添加到右键菜单 deserves to know it only landed in the classic
  ; menu. Silent installs must stay silent, so no dialog there.
  IfSilent shellMenuDone
  MessageBox MB_ICONEXCLAMATION|MB_OK "Sopeek 已安装完成，但 Windows 11 新版右键菜单的注册未成功。$\r$\n$\r$\n经典（显示更多选项）右键菜单仍然可用。$\r$\n诊断信息：$INSTDIR\shell_menu_status.txt"
  Goto shellMenuDone
shellMenuSkipOs:
  DetailPrint "Shell menu package skipped: Windows 10 has no modern context menu"
  ; 旧版本（2.0.0 之前）没有做系统门禁，Windows 10 上可能残留一个已注册的同名
  ; 包入口（开始菜单会多一个重名图标）。这里主动撤掉，保证「有且只有一个」。
  IfFileExists "$INSTDIR\shell_menu_unregister.ps1" 0 shellMenuSkipOsNoUnreg
  nsExec::ExecToStack '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$INSTDIR\shell_menu_unregister.ps1" -InstallDir "$INSTDIR"'
  Pop $1
  Pop $2
shellMenuSkipOsNoUnreg:
  FileOpen $3 "$INSTDIR\shell_menu_status.txt" w
  FileWrite $3 "status=skipped-os$\r$\n"
  FileClose $3
  Goto shellMenuDone
shellMenuMissing:
  DetailPrint "Shell menu package missing from $INSTDIR"
  FileOpen $3 "$INSTDIR\shell_menu_status.txt" w
  FileWrite $3 "status=missing$\r$\n"
  FileClose $3
  IfSilent shellMenuDone
  MessageBox MB_ICONEXCLAMATION|MB_OK "安装包缺少新版右键菜单所需的组件，Windows 11 新版右键菜单将不可用。$\r$\n$\r$\n经典（显示更多选项）右键菜单仍然可用。"
shellMenuDone:
FunctionEnd

; Remove the sparse package when the user installs/repairs with the context-menu
; checkbox cleared. Shares the uninstall-time script: it drops the package for the
; current user and removes the exact certificate thumbprint recorded at install.
; Missing script/files are a no-op (nothing was ever registered).
Function UnregisterShellMenuPackage
  IfFileExists "$INSTDIR\shell_menu_unregister.ps1" 0 unShellMenuKeepDone
  DetailPrint "Removing shell menu package"
  nsExec::ExecToStack '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$INSTDIR\shell_menu_unregister.ps1" -InstallDir "$INSTDIR"'
  Pop $1
  Pop $2
  StrCmp $1 "0" unShellMenuKeepDone
  DetailPrint "Shell menu package removal failed (exit=$1): $2"
unShellMenuKeepDone:
FunctionEnd

; A shell extension that is already mapped into explorer.exe keeps serving the
; OLD code even after its file is replaced: the shell caches the class factory per
; CLSID, so clicking the menu item runs the previous DLL (symptom: the new log
; lines never appear, and a background click that the old build could not resolve
; still does nothing). ParkStaleShellExt raises $R9=1 in exactly that case; the
; only reliable cure is to restart explorer so it loads the freshly installed DLL.
; Fresh installs never reach here with $R9=1, so nothing is restarted needlessly.

; Wait until the rebuilt shell is actually up. Killing explorer.exe clears the
; foreground window; re-activating the installer before the tray/desktop windows
; exist would just be refused again by the foreground lock.
Function WaitForShellReady
  StrCpy $4 0
shellWaitLoop:
  FindWindow $R0 "Shell_TrayWnd" ""
  StrCmp $R0 0 shellWaitTick
  FindWindow $R1 "Progman" ""
  StrCmp $R1 0 shellWaitTick
  Return
shellWaitTick:
  Sleep 300
  IntOp $4 $4 + 300
  IntCmp $4 12000 shellWaitGiveUp 0 shellWaitGiveUp
  Goto shellWaitLoop
shellWaitGiveUp:
  DetailPrint "Shell did not report ready within 12s; re-activating anyway"
FunctionEnd

; Bring the installer UI back to the foreground after the explorer restart.
;
; It must run in the GUI process: an inactive process cannot call
; SetForegroundWindow for a window it does not own (the foreground lock rejects
; it), which is exactly why the window could not be re-activated by clicking.
; The GUI registered this private message at startup; the message handler then
; tries SetForegroundWindow, AttachThreadInput and SwitchToThisWindow in order.
Function RestoreInstallerForeground
  FindWindow $R0 "SopeekInstaller" ""
  StrCmp $R0 0 restoreFgDone
  System::Call 'user32::RegisterWindowMessageW(w "SopeekInstallerRestoreForeground") i .r1'
  StrCmp $R1 0 restoreFgFallback
  ; PostMessage (not SendMessage): the setup process must never block on the GUI
  ; thread, and the GUI can re-activate itself whenever its loop picks the message up.
  System::Call 'user32::PostMessageW(p $R0, i $R1, p 0, p 0)'
  DetailPrint "Requested installer window re-activation"
  Goto restoreFgDone
restoreFgFallback:
  ; Extremely unlikely (registration failed): fall back to a cross-process raise.
  System::Call 'user32::SetForegroundWindow(p $R0)'
restoreFgDone:
FunctionEnd
Function RestartExplorerForShellExt
  StrCmp $R9 "1" 0 restartShellDone
  IfSilent restartShellSilent
  MessageBox MB_YESNO|MB_ICONQUESTION "右键菜单扩展已更新，但需要重启资源管理器才会加载新版本（旧版本可能仍被占用，或新版菜单尚未刷新）。$\r$\n$\r$\n现在重启资源管理器让新菜单立即生效吗？$\r$\n（会关闭当前打开的资源管理器窗口，随后自动重新打开；选“否”则重启电脑后生效。）" IDNO restartShellDeclined
restartShellSilent:
  DetailPrint "Restarting explorer to load the new shell extension"
  nsExec::ExecToStack 'taskkill /f /im explorer.exe'
  Pop $1
  Pop $2
  Sleep 1500
  Exec '"$WINDIR\explorer.exe"'
  ; Wait for the shell to actually come back before touching activation: killing
  ; explorer.exe clears the foreground window, and the rebuilt shell may grab it
  ; again. Polling the desktop/taskbar windows is the cheapest reliable signal.
  Call WaitForShellReady
  ; Explorer 冷启动会在数秒内陆续创建任务栏/桌面窗口，并反复把前台抢回去；
  ; 单次请求很容易被后到的 shell 窗口覆盖，所以分几次投递，每次都让 GUI 重新
  ; 打开一轮重试窗口（GUI 侧已在最前面判断「已是前台就立刻返回」）。
  Call RestoreInstallerForeground
  Sleep 1200
  Call RestoreInstallerForeground
  Sleep 2000
  Call RestoreInstallerForeground
  Sleep 3000
  Call RestoreInstallerForeground
  Goto restartShellDone
restartShellDeclined:
  FileOpen $3 "$INSTDIR\shell_menu_status.txt" a
  FileWrite $3 "explorer_restart=pending$\r$\n"
  FileClose $3
restartShellDone:
FunctionEnd
!endif

; T15 helper: same payload release + sentinel as the pre-T15 fresh-install flow.
Function ReleasePayload
  Delete "$PLUGINSDIR\payload.error"
  SetOutPath "$PLUGINSDIR\payload"
  File /r "${PAYLOAD}\*"
  ; A silent/partial extraction must never leave the GUI waiting for a sentinel
  ; that will never appear. Verify the primary payload entry before signalling
  ; readiness; on failure write payload.error so the GUI can fail fast with a
  ; user-facing message instead of sitting at 50% until the long timeout.
  IfFileExists "$PLUGINSDIR\payload\Sopeek.exe" 0 payloadReleaseFailed
  IfFileExists "$PLUGINSDIR\payload\_internal\*.*" 0 payloadReleaseFailed
  ; Payload-ready sentinel: written AFTER the payload release above completes and
  ; OUTSIDE the payload directory. The GUI waits for this before pre-scanning and
  ; copying. WriteINIStr takes 4 parameters: file / section / key / value.
  WriteINIStr "$PLUGINSDIR\payload.ready" "ready" "ready" "1"
  Return
payloadReleaseFailed:
  WriteINIStr "$PLUGINSDIR\payload.error" "error" "message" "payload-release-failed"
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
  FindWindow $R0 "SopeekInstaller" ""
  StrCmp $R0 0 0 waitAlive
  ; Window not found: only judgeable once it has been seen at least once.
  StrCmp $Seen 1 0 waitNoWindowCheck
  IntOp $3 $3 + 1
  IntCmp $3 30 waitCrash 0 waitCrash
  Goto waitTick
waitNoWindowCheck:
  ; H5: first-window deadline. A process that never shows a UI (blocked before
  ; window creation, silent crash, wrong image) fails fast and nonzero.
  IntCmp $2 ${SPK_GUI_WINDOW_DETECT_MS} waitNoWindow waitTick waitNoWindow
waitAlive:
  StrCpy $Seen 1
  StrCpy $3 0
waitTick:
  Sleep 100
  IntOp $2 $2 + 100
  IntCmp $2 ${SPK_WAIT_TIMEOUT_MS} 0 0 waitTimeout
  Goto waitLoop
waitTimeout:
  ; Bounded fallback: no terminal key within SPK_WAIT_TIMEOUT_MS -> silent abort.
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
  ; GUI binary. Test branch embeds the SPK_TESTMODE build from
  ; tools/build_test_gui.ps1 (repo-root build/test-installer, a separate output
  ; dir from the production build/installer artifact). Production branch
  ; unchanged. The MinGW runtime follows the same branch.
!ifdef SPK_TESTMODE
  File "..\..\build\test-installer\SopeekInstaller.exe"
  File "..\..\build\test-installer\libwinpthread-1.dll"
!else
  File "..\..\build\installer\SopeekInstaller.exe"
  File "..\..\build\installer\libwinpthread-1.dll"
!endif
  Call PrepareGuiCopy
  Call ParkStaleShellExt

  ; T15 installed detection is exactly: app exe OR _internal. No other signal
  ; (result INI, shortcuts, Add/Remove entry) may force maintenance mode.
  ;
  ; Existing installations always enter maintenance. The GUI compares versions
  ; and offers only the valid actions for this package.
  IfFileExists "$INSTDIR\Sopeek.exe" installed
  IfFileExists "$INSTDIR\_internal" installed

  ; Fresh install.
  ; The only difference is that the GUI now runs from the temp copy (with
  ; libwinpthread-1.dll next to it).
  ; Test branch drives the GUI unattended: /auto:opts=<bits> (contract §17)
  ; automates 欢迎→…→完成 with the frozen option bits (default 1101);
  ; production branch stays interactive (no /auto flag).
!ifdef SPK_TESTMODE
  ; T20 runtime override: SPK_QA_INSTALL_OPTS lets one test setup install with
  ; option bits that avoid touching the real desktop/start-menu (e.g. 0000).
  ; Empty/unset keeps the frozen SPK_AUTO_PROFILE contract.
  ReadEnvStr $R3 "SPK_QA_INSTALL_OPTS"
  StrCmp $R3 "" 0 installOptsReady
  StrCpy $R3 "${SPK_AUTO_PROFILE}"
installOptsReady:
  ClearErrors
  Exec '"$GuiTempExe" /payload "$PLUGINSDIR\payload" /result "${RESULT_INI}" /installdir "$INSTDIR" /setup-pid $SetupPid /payload-bytes ${PAYLOAD_BYTES} /auto:opts=$R3'
!else
  ClearErrors
  Exec '"$GuiTempExe" /payload "$PLUGINSDIR\payload" /result "${RESULT_INI}" /installdir "$INSTDIR" /setup-pid $SetupPid /payload-bytes ${PAYLOAD_BYTES}'
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
!ifdef SPK_TESTMODE
  ; T20 runtime hook: /auto:mode=maintenance + action for unattended QA.
  ReadEnvStr $R2 "SPK_QA_MAINTENANCE_EXTRA"
  ClearErrors
  Exec '"$GuiTempExe" /maintenance /package-version "${SPK_PRODUCT_VERSION}" /payload "$PLUGINSDIR\payload" /result "${RESULT_INI}" /installdir "$INSTDIR" /decision "$DecisionIni" /setup-pid $SetupPid /payload-bytes ${PAYLOAD_BYTES} $R2'
!else
  ClearErrors
  Exec '"$GuiTempExe" /maintenance /package-version "${SPK_PRODUCT_VERSION}" /payload "$PLUGINSDIR\payload" /result "${RESULT_INI}" /installdir "$INSTDIR" /decision "$DecisionIni" /setup-pid $SetupPid /payload-bytes ${PAYLOAD_BYTES}'
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
  FindWindow $R0 "SopeekInstaller" ""
  StrCmp $R0 0 0 decisionAlive
  ; Not-yet-seen is not a failure; seen-then-gone without action is.
  StrCmp $Seen 1 0 decisionNoWindowCheck
  IntOp $3 $3 + 1
  IntCmp $3 30 decisionGuiGone 0 decisionGuiGone
  Goto decisionTick
decisionNoWindowCheck:
  ; H5: same first-window deadline as WaitForInstallResult (200ms ticks).
  IntCmp $2 ${SPK_GUI_WINDOW_DETECT_MS} decisionNoWindow decisionTick decisionNoWindow
decisionAlive:
  StrCpy $Seen 1
  StrCpy $3 0
decisionTick:
  Sleep 200
  IntOp $2 $2 + 200
  IntCmp $2 ${SPK_DECISION_TIMEOUT_MS} 0 0 decisionTimeout
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
  StrCmp $0 "repair" decisionApply
  StrCmp $0 "update" decisionApply decisionNonRepair
 decisionApply:
  ; repair/update: ack FIRST, then release payload + sentinel, then the unchanged
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

; Remove the Windows 11 modern-menu sparse package (and the signing certificate it
; trusted). Called from uninstall Stage 3 while shell_menu_unregister.ps1 and the
; package manifest still exist in $INSTDIR. Failures are logged only: the menu
; integration is optional and must never turn a working uninstall into an error.
Function un.RemoveShellMenuPackage
  IfFileExists "$INSTDIR\shell_menu_unregister.ps1" 0 unShellMenuSkip
  DetailPrint "Removing shell menu package"
  nsExec::ExecToStack '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$INSTDIR\shell_menu_unregister.ps1" -InstallDir "$INSTDIR"'
  Pop $1
  Pop $2
  StrCmp $1 "0" unShellMenuSkip
  DetailPrint "Shell menu package removal failed (exit=$1): $2"
unShellMenuSkip:
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
; Used to avoid deleting a target that contains a custom SPK_DATA_DIR (or is
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
; from. Only an exact $TEMP\SopeekMaintenance-<digits> parent is
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
  StrCpy $1 "$TEMP\SopeekMaintenance-"
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
  FindWindow $R0 "SopeekInstaller" ""
  StrCmp $R0 0 0 unReqSeen
  StrCmp $2 1 0 unReqTick
  IntOp $1 $1 + 1
  IntCmp $1 30 unReqGone 0 unReqGone
  Goto unReqTick
unReqSeen:
  StrCpy $2 1
  StrCpy $1 0
unReqTick:
  Sleep ${SPK_UNINSTALL_POLL_MS}
  IntOp $0 $0 + ${SPK_UNINSTALL_POLL_MS}
  IntCmp $0 ${SPK_UNINSTALL_REQUEST_TIMEOUT_MS} 0 0 unReqTimeout
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
  ; Double-clicking UninstallHelper.exe in the install directory passes no arguments.
  ; Without this default the helper branch would wait forever for a UI request that
  ; never arrives (the user sees "double-clicking the uninstaller does nothing").
  ; Note: this script is compiled as ACP, so keep comments ASCII-only.
  StrCmp $UnArgMode "" 0 unArgModeDone
  StrCmp $UnArgSilent "1" unArgModeDone
  StrCpy $UnArgMode "launcher"
unArgModeDone:
  StrCmp $UnArgInstallDir "" unArgDirDone
  StrCpy $INSTDIR $UnArgInstallDir
unArgDirDone:
  StrCpy $UnRequestIni "$INSTDIR\${UNINSTALL_REQUEST_FILE}"
  StrCpy $UnResultIni "$INSTDIR\${UNINSTALL_RESULT_FILE}"
  StrCpy $UnUiExe "$INSTDIR\SopeekUninstall.exe"
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
  System::Call 'kernel32::WaitForSingleObject(p $1, i ${SPK_UNINSTALL_SETUP_MUTEX_WAIT_MS}) i .r3'
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
!ifdef SPK_TESTMODE
  StrCpy $3 '$3 ${SPK_QA_UI_EXTRA}'
  ; T20 runtime hook: /auto:mode=uninstall /auto:action=uninstall
  ; /auto:delete-user-data=... selected by the QA harness.
  ReadEnvStr $R4 "SPK_QA_UI_RUNTIME_EXTRA"
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
!ifdef SPK_TESTMODE
  SetRegView 64
!else
  ; Upgrade orphan cleanup: an older installer may have left the Uninstall entry in
  ; the 32-bit view (Wow6432Node); remove that same-named entry first so an upgrade
  ; cannot produce a duplicate Add/Remove Programs item.
  SetRegView 32
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Sopeek"
  SetRegView 64
!endif

  ; T16: install the uninstall stack (UI + MinGW runtime + NSIS helper) before any
  ; Add/Remove metadata is written. The UI/DLL are copied to temporary names first
  ; and renamed into place only after the complete copy is verified, so a partial
  ; file can never be referenced by UninstallString.
  CreateDirectory "$INSTDIR"
  Delete "$INSTDIR\SopeekUninstall.exe.tmp"
  Delete "$INSTDIR\libwinpthread-1.dll.tmp"
  CopyFiles /SILENT "$PLUGINSDIR\SopeekInstaller.exe" "$INSTDIR\SopeekUninstall.exe.tmp"
  CopyFiles /SILENT "$PLUGINSDIR\libwinpthread-1.dll" "$INSTDIR\libwinpthread-1.dll.tmp"
  IfFileExists "$INSTDIR\SopeekUninstall.exe.tmp" 0 uninstallPayloadFailed
  IfFileExists "$INSTDIR\libwinpthread-1.dll.tmp" 0 uninstallPayloadFailed

!ifdef SPK_TESTMODE
  ; T20/F1: deterministic UI-payload failure injection (test builds only;
  ; production compiles this block out). Proves that aborting here leaves no
  ; UninstallString/uninstall key and no uninstaller executable behind.
  ReadEnvStr $R2 "SPK_QA_FAIL_UI_COPY"
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

  Delete "$INSTDIR\SopeekUninstall.exe.old"
  Rename "$INSTDIR\SopeekUninstall.exe" "$INSTDIR\SopeekUninstall.exe.old"
  ClearErrors
  Rename "$INSTDIR\SopeekUninstall.exe.tmp" "$INSTDIR\SopeekUninstall.exe"
  IfErrors uninstallUiRenameFailed

  IfFileExists "$INSTDIR\SopeekUninstall.exe" 0 uninstallPayloadFailed
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
  Delete "$INSTDIR\SopeekUninstall.exe.old"
  Delete "$INSTDIR\libwinpthread-1.dll.old"

  ; Optional desktop shortcut (flag from the result INI). A stale shortcut from an
  ; earlier install is removed when the flag is 0. Test builds use the isolated
  ; SopeekTest.lnk and can never touch the production shortcut.
  ReadINIStr $0 "${RESULT_INI}" "install" "desktop"
  StrCmp $0 "1" 0 desktopRemove
  CreateShortcut "$DESKTOP\${SHORTCUT_STEM}.lnk" "$INSTDIR\Sopeek.exe"
  Goto desktopDone
desktopRemove:
  Delete "$DESKTOP\${SHORTCUT_STEM}.lnk"
desktopDone:
  ; Optional Start Menu shortcut. Production owns only its own Sopeek
  ; folder; test builds use a flat SopeekTest.lnk and never create or
  ; remove a production folder.
  ReadINIStr $0 "${RESULT_INI}" "install" "startmenu"
  StrCmp $0 "1" 0 startmenuRemove
!ifdef SPK_TESTMODE
  CreateShortcut "$SMPROGRAMS\${SHORTCUT_STEM}.lnk" "$INSTDIR\Sopeek.exe"
!else
  CreateDirectory "$SMPROGRAMS\${SHORTCUT_STEM}"
  CreateShortcut "$SMPROGRAMS\${SHORTCUT_STEM}\${SHORTCUT_STEM}.lnk" "$INSTDIR\Sopeek.exe"
!endif
  Goto startmenuDone
startmenuRemove:
!ifdef SPK_TESTMODE
  Delete "$SMPROGRAMS\${SHORTCUT_STEM}.lnk"
!else
  Delete "$SMPROGRAMS\${SHORTCUT_STEM}\${SHORTCUT_STEM}.lnk"
  RMDir "$SMPROGRAMS\${SHORTCUT_STEM}"
!endif
startmenuDone:

  ; Optional Explorer context-menu integration, driven by the result INI (the GUI
  ; defaults ctxmenu to 1). A registration left behind by an earlier install is
  ; removed when the flag is 0. Both commands are served by SopeekShellExt.dll,
  ; which the payload installs next to Sopeek.exe:
  ;   * "用Sopeek软件打开" for any file  (*\shell\SopeekOpenFile)
  ;   * "使用Sopeek打开"   for a folder  (Directory\shell\SopeekOpenFolder)
  ;                        and its empty background
  ;                        (Directory\Background\shell\SopeekOpenFolder)
  ; ExplorerCommandHandler is the value the Windows 11 modern menu reads; the
  ; command subkey keeps the Windows 10 classic menu (and older builds) working
  ; without a COM handler. Production writes the machine-wide HKLM keys in the
  ; native 64-bit view selected above; test builds write isolated HKCU keys and
  ; can never touch a production key.
  ReadINIStr $0 "${RESULT_INI}" "install" "ctxmenu"
  StrCmp $0 "1" 0 ctxmenuRemove

  ; One CLSID per command: the title is then fixed and independent of context.
  WriteRegStr ${SPK_CTX_ROOT} "Software\Classes\CLSID\${SPK_CTX_FILE_CLSID}" "" "Sopeek file context menu"
  WriteRegStr ${SPK_CTX_ROOT} "Software\Classes\CLSID\${SPK_CTX_FILE_CLSID}\InprocServer32" "" '"$INSTDIR\${SPK_SHELLEXT_DLL}"'
  WriteRegStr ${SPK_CTX_ROOT} "Software\Classes\CLSID\${SPK_CTX_FILE_CLSID}\InprocServer32" "ThreadingModel" "Apartment"
  WriteRegStr ${SPK_CTX_ROOT} "Software\Classes\CLSID\${SPK_CTX_FOLDER_CLSID}" "" "Sopeek folder context menu"
  WriteRegStr ${SPK_CTX_ROOT} "Software\Classes\CLSID\${SPK_CTX_FOLDER_CLSID}\InprocServer32" "" '"$INSTDIR\${SPK_SHELLEXT_DLL}"'
  WriteRegStr ${SPK_CTX_ROOT} "Software\Classes\CLSID\${SPK_CTX_FOLDER_CLSID}\InprocServer32" "ThreadingModel" "Apartment"

  ; Files: a standalone menu entry; no file-extension association is written.
  ; (Verbs are written after the sparse-package step: on Windows 11 the package
  ; commands already cover both menus, so writing them too would duplicate.)
  ; Folders: right-clicking the folder icon. %1 is the folder itself.
  ; Empty space inside a folder: %V is the folder; the COM handler resolves the
  ; same folder through the Explorer site (IShellView / ShellWindows fallback).

  ; Windows 11 modern menu: register the sparse package BEFORE the verbs so a
  ; registration failure can be reported in the same step. Production only:
  ; test builds must stay HKCU-isolated and never require elevation.
!ifndef SPK_TESTMODE
  Call RegisterShellMenuPackage
!endif

  ; 注册表动词照常写入：它们是 Windows 10 与「显示更多选项」的可靠回退，也是
  ; 包注册被策略拦下时唯一还能用的入口。若 Windows 11 同时枚举包命令与注册表
  ; 动词、导致经典菜单出现重复条目，再按实测结果收敛（宁可重复，不可缺失）。
  WriteRegStr ${SPK_CTX_ROOT} "Software\Classes\*\shell\${SPK_CTX_FILE_VERB}" "" "用Sopeek软件打开"
  WriteRegStr ${SPK_CTX_ROOT} "Software\Classes\*\shell\${SPK_CTX_FILE_VERB}" "Icon" '"$INSTDIR\Sopeek.exe",0'
  WriteRegStr ${SPK_CTX_ROOT} "Software\Classes\*\shell\${SPK_CTX_FILE_VERB}" "ExplorerCommandHandler" "${SPK_CTX_FILE_CLSID}"
  WriteRegStr ${SPK_CTX_ROOT} "Software\Classes\*\shell\${SPK_CTX_FILE_VERB}" "MultiSelectModel" "Single"
  WriteRegStr ${SPK_CTX_ROOT} "Software\Classes\*\shell\${SPK_CTX_FILE_VERB}\command" "" '"$INSTDIR\Sopeek.exe" --open-path "%1"'

  WriteRegStr ${SPK_CTX_ROOT} "Software\Classes\Directory\shell\${SPK_CTX_FOLDER_VERB}" "" "使用Sopeek打开"
  WriteRegStr ${SPK_CTX_ROOT} "Software\Classes\Directory\shell\${SPK_CTX_FOLDER_VERB}" "Icon" '"$INSTDIR\Sopeek.exe",0'
  WriteRegStr ${SPK_CTX_ROOT} "Software\Classes\Directory\shell\${SPK_CTX_FOLDER_VERB}" "ExplorerCommandHandler" "${SPK_CTX_FOLDER_CLSID}"
  WriteRegStr ${SPK_CTX_ROOT} "Software\Classes\Directory\shell\${SPK_CTX_FOLDER_VERB}\command" "" '"$INSTDIR\Sopeek.exe" --open-path "%1"'

  WriteRegStr ${SPK_CTX_ROOT} "Software\Classes\Directory\Background\shell\${SPK_CTX_FOLDER_VERB}" "" "使用Sopeek打开"
  WriteRegStr ${SPK_CTX_ROOT} "Software\Classes\Directory\Background\shell\${SPK_CTX_FOLDER_VERB}" "Icon" '"$INSTDIR\Sopeek.exe",0'
  WriteRegStr ${SPK_CTX_ROOT} "Software\Classes\Directory\Background\shell\${SPK_CTX_FOLDER_VERB}" "ExplorerCommandHandler" "${SPK_CTX_FOLDER_CLSID}"
  WriteRegStr ${SPK_CTX_ROOT} "Software\Classes\Directory\Background\shell\${SPK_CTX_FOLDER_VERB}\command" "" '"$INSTDIR\Sopeek.exe" --open-path "%V"'
  Goto ctxmenuLegacyCleanup

ctxmenuLegacyCleanup:
  ; Drop the pre-2.0 ("用 Sopeek 打开") verbs, which pointed at Directory\shell
  ; instead of the background and never passed --open-path.
  ClearErrors
  DeleteRegKey ${SPK_CTX_ROOT} "Software\Classes\Directory\shell\${SPK_CTX_LEGACY_VERB}"
  DeleteRegKey ${SPK_CTX_ROOT} "Software\Classes\Directory\Background\shell\${SPK_CTX_LEGACY_VERB}"
  DeleteRegKey ${SPK_CTX_ROOT} "Software\Classes\*\shell\${SPK_CTX_LEGACY_VERB}"
  Goto ctxmenuDone
ctxmenuRemove:
  ; Idempotent cleanup: deleting a parent verb key also removes its command
  ; subkey, and a missing key is a no-op (the option was never enabled).
  ClearErrors
  DeleteRegKey ${SPK_CTX_ROOT} "Software\Classes\*\shell\${SPK_CTX_FILE_VERB}"
  DeleteRegKey ${SPK_CTX_ROOT} "Software\Classes\Directory\shell\${SPK_CTX_FOLDER_VERB}"
  DeleteRegKey ${SPK_CTX_ROOT} "Software\Classes\Directory\Background\shell\${SPK_CTX_FOLDER_VERB}"
  DeleteRegKey ${SPK_CTX_ROOT} "Software\Classes\Directory\shell\${SPK_CTX_LEGACY_VERB}"
  DeleteRegKey ${SPK_CTX_ROOT} "Software\Classes\Directory\Background\shell\${SPK_CTX_LEGACY_VERB}"
  DeleteRegKey ${SPK_CTX_ROOT} "Software\Classes\*\shell\${SPK_CTX_LEGACY_VERB}"
  DeleteRegKey ${SPK_CTX_ROOT} "Software\Classes\CLSID\${SPK_CTX_FILE_CLSID}"
  DeleteRegKey ${SPK_CTX_ROOT} "Software\Classes\CLSID\${SPK_CTX_FOLDER_CLSID}"
ctxmenuDone:
  ; Ask the shell to re-read associations/menu registrations. SHCNE_ASSOCCHANGED
  ; (0x08000000) + SHCNF_IDLIST (0) is enough for the new verbs to appear (or
  ; disappear) without an Explorer restart.
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'

  ; Windows 11 modern menu follow-up. Production only — test builds must stay
  ; HKCU-isolated and never require elevation. The package itself was already
  ; registered above (before the verbs); here we only tear it down when the
  ; checkbox was cleared, or reload Explorer so the freshly written
  ; registrations are picked up.
!ifndef SPK_TESTMODE
  StrCmp $0 "1" shellMenuReload
  ; The user cleared the checkbox: an already-registered sparse package has to go
  ; too, otherwise its manifest-declared entries keep showing in the modern menu
  ; while the CLSIDs they point at were just deleted (clicking would do nothing).
  Call UnregisterShellMenuPackage
  Goto shellMenuSkip
shellMenuReload:
  ; The new DLL only takes effect once explorer reloads it, and the newly
  ; registered package commands only appear after the shell re-reads the manifest.
  Call RestartExplorerForShellExt
shellMenuSkip:
!endif

  ; T16: install-info metadata. Test builds use the isolated per-user test key;
  ; production uses the production key.
!ifdef SPK_TESTMODE
  WriteRegStr HKCU "Software\SopeekTest" "InstallDir" "$INSTDIR"
!else
  WriteRegStr HKCU "Software\Sopeek" "InstallDir" "$INSTDIR"
!endif

  ; Add/Remove Programs metadata. Production: native 64-bit HKLM view. Test: the
  ; same value names under the per-user HKCU test key; never a production key.
!ifdef SPK_TESTMODE
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\SopeekTest" "DisplayName" "Sopeek"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\SopeekTest" "UninstallString" '"$INSTDIR\UninstallHelper.exe" /uninstall-launcher /installdir "$INSTDIR" /ui "$INSTDIR\SopeekUninstall.exe"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\SopeekTest" "QuietUninstallString" '"$INSTDIR\UninstallHelper.exe" /S /installdir "$INSTDIR"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\SopeekTest" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\SopeekTest" "DisplayIcon" '"$INSTDIR\Sopeek.exe"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\SopeekTest" "DisplayVersion" "${SPK_PRODUCT_VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\SopeekTest" "Publisher" "Dorufoc & renmoren"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\SopeekTest" "URLInfoAbout" "https://github.com/Dorufoc/Sopeek"
  ; EstimatedSize is a DWORD in KB (${GetSize} with /S=0K returns the total in KB in $0).
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\SopeekTest" "EstimatedSize" $0
!else
  ; Add/Remove Programs metadata (production: native 64-bit HKLM view).
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Sopeek" "DisplayName" "Sopeek"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Sopeek" "UninstallString" '"$INSTDIR\UninstallHelper.exe" /uninstall-launcher /installdir "$INSTDIR" /ui "$INSTDIR\SopeekUninstall.exe"'
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Sopeek" "QuietUninstallString" '"$INSTDIR\UninstallHelper.exe" /S /installdir "$INSTDIR"'
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Sopeek" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Sopeek" "DisplayIcon" '"$INSTDIR\Sopeek.exe"'
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Sopeek" "DisplayVersion" "${SPK_PRODUCT_VERSION}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Sopeek" "Publisher" "Dorufoc & renmoren"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Sopeek" "URLInfoAbout" "https://github.com/Dorufoc/Sopeek"
  ; EstimatedSize is a DWORD in KB (${GetSize} with /S=0K returns the total in KB in $0).
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Sopeek" "EstimatedSize" $0
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
  ReadINIStr $7 "${RESULT_INI}" "install" "ctxmenu"
  StrCmp $7 "1" optCtxMenuOn
  StrCpy $7 0
optCtxMenuOn:
!ifdef SPK_TESTMODE
  WriteRegDWORD HKCU "Software\SopeekTest" "OptDesktop" $4
  WriteRegDWORD HKCU "Software\SopeekTest" "OptStartmenu" $5
  WriteRegDWORD HKCU "Software\SopeekTest" "OptAutostart" $6
  WriteRegDWORD HKCU "Software\SopeekTest" "OptCtxMenu" $7
!else
  WriteRegDWORD HKCU "Software\Sopeek" "OptDesktop" $4
  WriteRegDWORD HKCU "Software\Sopeek" "OptStartmenu" $5
  WriteRegDWORD HKCU "Software\Sopeek" "OptAutostart" $6
  WriteRegDWORD HKCU "Software\Sopeek" "OptCtxMenu" $7
!endif

  ; Optional autostart Run value (production only). Test builds must never read,
  ; write, or delete the production Run value; OptAutostart is still persisted in
  ; the isolated test install-info key above.
!ifdef SPK_TESTMODE
  ; Intentionally no Run side effect in test builds.
!else
  ; When disabled, delete only a value that is OURS (quote-consistent compare) -
  ; a value pointing elsewhere is never touched.
  StrCmp $6 "1" 0 autostartOff
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "Sopeek" '"$INSTDIR\Sopeek.exe"'
  Goto autostartDone
autostartOff:
  ReadRegStr $1 HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "Sopeek"
  StrCmp $1 '"$INSTDIR\Sopeek.exe"' 0 autostartDone
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "Sopeek"
autostartDone:
!endif

  ; Successful install: the maintenance handoff file has served its purpose.
  Delete "$INSTDIR\maintenance-decision.ini"
  Goto installDone

uninstallDllRenameFailed:
  Rename "$INSTDIR\libwinpthread-1.dll.old" "$INSTDIR\libwinpthread-1.dll"
  Goto uninstallPayloadFailed
uninstallUiRenameFailed:
  Rename "$INSTDIR\SopeekUninstall.exe.old" "$INSTDIR\SopeekUninstall.exe"
  Goto uninstallPayloadFailed
uninstallHelperFailed:
  SetErrorLevel 2
  Delete "$INSTDIR\SopeekUninstall.exe.old"
  Delete "$INSTDIR\libwinpthread-1.dll.old"
  Abort
uninstallPayloadFailed:
  SetErrorLevel 2
  Delete "$INSTDIR\SopeekUninstall.exe.tmp"
  Delete "$INSTDIR\libwinpthread-1.dll.tmp"
  Abort
installDone:
SectionEnd

Section "Uninstall"
  ; Defensive fallback for a Section reached without un.onInit (not expected).
  StrCmp $UnResultIni "" 0 unSecPathsReady
  StrCpy $UnRequestIni "$INSTDIR\${UNINSTALL_REQUEST_FILE}"
  StrCpy $UnResultIni "$INSTDIR\${UNINSTALL_RESULT_FILE}"
  StrCpy $UnUiExe "$INSTDIR\SopeekUninstall.exe"
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
!ifdef SPK_TESTMODE
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
!ifndef SPK_TESTMODE
  ; A folder containing unrelated user files is left alone; it is not an error.
  RMDir "$SMPROGRAMS\${SHORTCUT_STEM}"
!endif

  ; ---- Stage 2: registry --------------------------------------------------
  StrCpy $0 "removing_registry"
  StrCpy $1 "300"
  Call un.WriteProgress
  SetRegView 64

  ; Explorer context-menu registrations written by Section Install, removed in the
  ; same native 64-bit view (production HKLM; test HKCU test keys). Deleting the
  ; parent verb key also removes its command subkey. A missing key is a normal
  ; no-op, so existence is checked first (DeleteRegKey on an absent key sets the
  ; error flag). The legacy "用 Sopeek 打开" verbs are removed as well so an
  ; upgrade cannot leave a half-working entry behind.
  ReadRegStr $2 ${SPK_CTX_ROOT} "Software\Classes\*\shell\${SPK_CTX_FILE_VERB}" ""
  StrCmp $2 "" unSecCtxFileDone
  ClearErrors
  DeleteRegKey ${SPK_CTX_ROOT} "Software\Classes\*\shell\${SPK_CTX_FILE_VERB}"
  IfErrors unSecCtxFileFail
  Goto unSecCtxFileDone
unSecCtxFileFail:
  StrCpy $UnErrorText "${SPK_CTX_ROOT}\Software\Classes\*\shell\${SPK_CTX_FILE_VERB}"
  Goto unSecFail
unSecCtxFileDone:

  ReadRegStr $2 ${SPK_CTX_ROOT} "Software\Classes\Directory\shell\${SPK_CTX_FOLDER_VERB}" ""
  StrCmp $2 "" unSecCtxFolderDone
  ClearErrors
  DeleteRegKey ${SPK_CTX_ROOT} "Software\Classes\Directory\shell\${SPK_CTX_FOLDER_VERB}"
  IfErrors unSecCtxFolderFail
  Goto unSecCtxFolderDone
unSecCtxFolderFail:
  StrCpy $UnErrorText "${SPK_CTX_ROOT}\Software\Classes\Directory\shell\${SPK_CTX_FOLDER_VERB}"
  Goto unSecFail
unSecCtxFolderDone:

  ReadRegStr $2 ${SPK_CTX_ROOT} "Software\Classes\Directory\Background\shell\${SPK_CTX_FOLDER_VERB}" ""
  StrCmp $2 "" unSecCtxBackgroundDone
  ClearErrors
  DeleteRegKey ${SPK_CTX_ROOT} "Software\Classes\Directory\Background\shell\${SPK_CTX_FOLDER_VERB}"
  IfErrors unSecCtxBackgroundFail
  Goto unSecCtxBackgroundDone
unSecCtxBackgroundFail:
  StrCpy $UnErrorText "${SPK_CTX_ROOT}\Software\Classes\Directory\Background\shell\${SPK_CTX_FOLDER_VERB}"
  Goto unSecFail
unSecCtxBackgroundDone:

  ReadRegStr $2 ${SPK_CTX_ROOT} "Software\Classes\Directory\shell\${SPK_CTX_LEGACY_VERB}" ""
  StrCmp $2 "" unSecLegacyDirDone
  ClearErrors
  DeleteRegKey ${SPK_CTX_ROOT} "Software\Classes\Directory\shell\${SPK_CTX_LEGACY_VERB}"
  IfErrors unSecLegacyDirFail
  Goto unSecLegacyDirDone
unSecLegacyDirFail:
  StrCpy $UnErrorText "${SPK_CTX_ROOT}\Software\Classes\Directory\shell\${SPK_CTX_LEGACY_VERB}"
  Goto unSecFail
unSecLegacyDirDone:

  ReadRegStr $2 ${SPK_CTX_ROOT} "Software\Classes\Directory\Background\shell\${SPK_CTX_LEGACY_VERB}" ""
  StrCmp $2 "" unSecLegacyBgDone
  ClearErrors
  DeleteRegKey ${SPK_CTX_ROOT} "Software\Classes\Directory\Background\shell\${SPK_CTX_LEGACY_VERB}"
  IfErrors unSecLegacyBgFail
  Goto unSecLegacyBgDone
unSecLegacyBgFail:
  StrCpy $UnErrorText "${SPK_CTX_ROOT}\Software\Classes\Directory\Background\shell\${SPK_CTX_LEGACY_VERB}"
  Goto unSecFail
unSecLegacyBgDone:

  ReadRegStr $2 ${SPK_CTX_ROOT} "Software\Classes\*\shell\${SPK_CTX_LEGACY_VERB}" ""
  StrCmp $2 "" unSecLegacyFileDone
  ClearErrors
  DeleteRegKey ${SPK_CTX_ROOT} "Software\Classes\*\shell\${SPK_CTX_LEGACY_VERB}"
  IfErrors unSecLegacyFileFail
  Goto unSecLegacyFileDone
unSecLegacyFileFail:
  StrCpy $UnErrorText "${SPK_CTX_ROOT}\Software\Classes\*\shell\${SPK_CTX_LEGACY_VERB}"
  Goto unSecFail
unSecLegacyFileDone:

  ReadRegStr $2 ${SPK_CTX_ROOT} "Software\Classes\CLSID\${SPK_CTX_FILE_CLSID}" ""
  StrCmp $2 "" unSecCtxFileClsidDone
  ClearErrors
  DeleteRegKey ${SPK_CTX_ROOT} "Software\Classes\CLSID\${SPK_CTX_FILE_CLSID}"
  IfErrors unSecCtxFileClsidFail
  Goto unSecCtxFileClsidDone
unSecCtxFileClsidFail:
  StrCpy $UnErrorText "${SPK_CTX_ROOT}\Software\Classes\CLSID\${SPK_CTX_FILE_CLSID}"
  Goto unSecFail
unSecCtxFileClsidDone:

  ReadRegStr $2 ${SPK_CTX_ROOT} "Software\Classes\CLSID\${SPK_CTX_FOLDER_CLSID}" ""
  StrCmp $2 "" unSecCtxFolderClsidDone
  ClearErrors
  DeleteRegKey ${SPK_CTX_ROOT} "Software\Classes\CLSID\${SPK_CTX_FOLDER_CLSID}"
  IfErrors unSecCtxFolderClsidFail
  Goto unSecCtxFolderClsidDone
unSecCtxFolderClsidFail:
  StrCpy $UnErrorText "${SPK_CTX_ROOT}\Software\Classes\CLSID\${SPK_CTX_FOLDER_CLSID}"
  Goto unSecFail
unSecCtxFolderClsidDone:

  ; Rebuild the shell's cached menu state so the entries disappear immediately.
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
!ifndef SPK_TESTMODE
  ; Run value: remove only the quote-consistent value written by Section Install.
  ReadRegStr $2 HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "Sopeek"
  StrCmp $2 '"$INSTDIR\Sopeek.exe"' 0 unSecRunDone
  ClearErrors
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "Sopeek"
  IfErrors unSecRunFail
  Goto unSecRunDone
unSecRunFail:
  StrCpy $UnErrorText "HKCU\Software\Microsoft\Windows\CurrentVersion\Run\Sopeek"
  Goto unSecFail
unSecRunDone:
!endif

  ; Add/Remove entry, native 64-bit view (production HKLM; test HKCU test key).
!ifdef SPK_TESTMODE
  ReadRegStr $2 HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\SopeekTest" "DisplayName"
  StrCmp $2 "" unSecUninst64Done
  ClearErrors
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\SopeekTest"
  IfErrors unSecUninst64Fail
  Goto unSecUninst64Done
unSecUninst64Fail:
  StrCpy $UnErrorText "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\SopeekTest"
  Goto unSecFail
unSecUninst64Done:
!else
  ReadRegStr $2 HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Sopeek" "DisplayName"
  StrCmp $2 "" unSecUninst64Done
  ClearErrors
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Sopeek"
  IfErrors unSecUninst64Fail
  Goto unSecUninst64Done
unSecUninst64Fail:
  StrCpy $UnErrorText "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\Sopeek"
  Goto unSecFail
unSecUninst64Done:
!endif

  ; Install-info key (InstallDir/Opt*); InstallLocation lives on the uninstall key.
!ifdef SPK_TESTMODE
  ReadRegStr $2 HKCU "Software\SopeekTest" "InstallDir"
  StrCmp $2 "" unSecInfoDone
  ClearErrors
  DeleteRegKey HKCU "Software\SopeekTest"
  IfErrors unSecInfoFail
  Goto unSecInfoDone
unSecInfoFail:
  StrCpy $UnErrorText "HKCU\Software\SopeekTest"
  Goto unSecFail
unSecInfoDone:
!else
  ReadRegStr $2 HKCU "Software\Sopeek" "InstallDir"
  StrCmp $2 "" unSecInfoDone
  ClearErrors
  DeleteRegKey HKCU "Software\Sopeek"
  IfErrors unSecInfoFail
  Goto unSecInfoDone
unSecInfoFail:
  StrCpy $UnErrorText "HKCU\Software\Sopeek"
  Goto unSecFail
unSecInfoDone:
!endif

  ; Legacy 32-bit HKLM view. HKCU is not WOW64-redirected; for test builds this
  ; repeats the same idempotent test-key deletion and normally finds nothing.
  SetRegView 32
!ifdef SPK_TESTMODE
  ReadRegStr $2 HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\SopeekTest" "DisplayName"
  StrCmp $2 "" unSecUninst32Done
  ClearErrors
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\SopeekTest"
  IfErrors unSecUninst32Fail
  Goto unSecUninst32Done
unSecUninst32Fail:
  StrCpy $UnErrorText "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\SopeekTest"
  Goto unSecFail
unSecUninst32Done:
!else
  ReadRegStr $2 HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Sopeek" "DisplayName"
  StrCmp $2 "" unSecUninst32Done
  ClearErrors
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Sopeek"
  IfErrors unSecUninst32Fail
  Goto unSecUninst32Done
unSecUninst32Fail:
  StrCpy $UnErrorText "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\Sopeek"
  Goto unSecFail
unSecUninst32Done:
!endif
  SetRegView 64

  ; ---- Stage 3: files -----------------------------------------------------
  StrCpy $0 "removing_files"
  StrCpy $1 "500"
  Call un.WriteProgress

  ; Windows 11 modern menu: unregister the sparse package while its scripts and
  ; manifest are still on disk (they are deleted below). Best effort — a package
  ; that was never registered, or a policy-blocked machine, must not fail the uninstall.
  Call un.RemoveShellMenuPackage

  ; _internal app files, preserving only _internal\data (handled by stage 4).
  StrCpy $R5 "$INSTDIR\_internal"
  StrCpy $R6 "data"
  StrCpy $R8 "0"
  IfFileExists "$R5" 0 unSecInternalDone
  Call un.DeleteTree
  StrCmp $UnFailedPath "" 0 unSecPathFail
unSecInternalDone:

  ; Shell extension DLL. Explorer may still have it mapped in-proc, so a normal
  ; delete can fail even though the registration is already gone. Fall back to a
  ; reboot-time delete and record it as a post-done warning, never a stage failure.
  IfFileExists "$INSTDIR\${SPK_SHELLEXT_DLL}" 0 unSecShellExtDone
  ClearErrors
  Delete "$INSTDIR\${SPK_SHELLEXT_DLL}"
  IfFileExists "$INSTDIR\${SPK_SHELLEXT_DLL}" 0 unSecShellExtDone
  Delete /REBOOTOK "$INSTDIR\${SPK_SHELLEXT_DLL}"
  IfFileExists "$INSTDIR\${SPK_SHELLEXT_DLL}" 0 unSecShellExtDone
  StrCpy $0 "reboot_pending"
  Call un.AddWarning
unSecShellExtDone:

  ; 升级时 ParkStaleShellExt 会把仍被 Explorer 映射的旧 DLL 改名成 .old；
  ; 若卸载不清掉它，目录非空会让 RMDir 失败并落到 install-dir-not-empty 警告，
  ; 连带 QA 的 Finish 页断言变得不稳定。这里同样先删、再排队重启删除。
  IfFileExists "$INSTDIR\${SPK_SHELLEXT_DLL}.old" 0 unSecShellExtOldDone
  ClearErrors
  Delete "$INSTDIR\${SPK_SHELLEXT_DLL}.old"
  IfFileExists "$INSTDIR\${SPK_SHELLEXT_DLL}.old" 0 unSecShellExtOldDone
  Delete /REBOOTOK "$INSTDIR\${SPK_SHELLEXT_DLL}.old"
  IfFileExists "$INSTDIR\${SPK_SHELLEXT_DLL}.old" 0 unSecShellExtOldDone
  StrCpy $0 "reboot_pending"
  Call un.AddWarning
unSecShellExtOldDone:

  IfFileExists "$INSTDIR\Sopeek.exe" 0 unSecAppDone
  Delete "$INSTDIR\Sopeek.exe"
  IfFileExists "$INSTDIR\Sopeek.exe" 0 unSecAppDone
  StrCpy $UnErrorText "$INSTDIR\Sopeek.exe"
  Goto unSecFail
unSecAppDone:

  IfFileExists "$INSTDIR\Uninstall.exe" 0 unSecLegacyDone
  Delete "$INSTDIR\Uninstall.exe"
  IfFileExists "$INSTDIR\Uninstall.exe" 0 unSecLegacyDone
  StrCpy $UnErrorText "$INSTDIR\Uninstall.exe"
  Goto unSecFail
unSecLegacyDone:

  ; Retired install-stack leftovers are app-owned; report the exact leftover.
  Delete "$INSTDIR\SopeekUninstall.exe.old"
  IfFileExists "$INSTDIR\SopeekUninstall.exe.old" 0 unSecTempUiOldDone
  StrCpy $UnErrorText "$INSTDIR\SopeekUninstall.exe.old"
  Goto unSecFail
unSecTempUiOldDone:
  Delete "$INSTDIR\libwinpthread-1.dll.old"
  IfFileExists "$INSTDIR\libwinpthread-1.dll.old" 0 unSecTempDllOldDone
  StrCpy $UnErrorText "$INSTDIR\libwinpthread-1.dll.old"
  Goto unSecFail
unSecTempDllOldDone:
  Delete "$INSTDIR\SopeekUninstall.exe.tmp"
  IfFileExists "$INSTDIR\SopeekUninstall.exe.tmp" 0 unSecTempUiTmpDone
  StrCpy $UnErrorText "$INSTDIR\SopeekUninstall.exe.tmp"
  Goto unSecFail
unSecTempUiTmpDone:
  Delete "$INSTDIR\libwinpthread-1.dll.tmp"
  IfFileExists "$INSTDIR\libwinpthread-1.dll.tmp" 0 unSecTempDllTmpDone
  StrCpy $UnErrorText "$INSTDIR\libwinpthread-1.dll.tmp"
  Goto unSecFail
unSecTempDllTmpDone:
  ; Windows 11 modern-menu integration files. The package itself was unregistered
  ; at the top of this stage, so these are inert leftovers; a locked file becomes a
  ; reboot-pending warning instead of failing the uninstall.
  Delete "$INSTDIR\SopeekShellMenu.msix"
  Delete "$INSTDIR\SopeekShellMenu.cer"
  Delete "$INSTDIR\shell_menu_register.ps1"
  Delete "$INSTDIR\shell_menu_unregister.ps1"
  Delete "$INSTDIR\shell_menu_installed.txt"
  Delete "$INSTDIR\shell_menu_status.txt"
  ; Resource index for the external location: without it the taskbar falls back to
  ; the plated logo (accent-colour square behind the icon).
  Delete "$INSTDIR\resources.pri"
  IfFileExists "$INSTDIR\SopeekShellMenu.msix" 0 unSecShellMenuFilesDone
  Delete /REBOOTOK "$INSTDIR\SopeekShellMenu.msix"
unSecShellMenuFilesDone:
  IfFileExists "$INSTDIR\SopeekShellMenu.msix" 0 unSecShellMenuCerDone
  StrCpy $0 "reboot_pending"
  Call un.AddWarning
unSecShellMenuCerDone:
  ; Sparse package logo set shipped next to Sopeek.exe (taskbar icon for windows
  ; started through the packaged command). Inert once the package is unregistered.
  RMDir /r "$INSTDIR\Assets"
  Goto unSecUserData

  ; ---- Stage 4: user data -------------------------------------------------
unSecUserData:
  StrCpy $0 "removing_user_data"
  StrCpy $1 "800"
  Call un.WriteProgress
  StrCmp $UnDeleteUserData "1" 0 unSecFinishing

  ReadEnvStr $UnSpkDataDir "SPK_DATA_DIR"
  StrCpy $R5 $UnSpkDataDir
  Call un.StripTrailingSlash
  StrCpy $UnSpkDataDir $R5

  ; Canonical per-user data root (test build has its own root).
  StrCpy $UnTarget "${UNINSTALL_DATA_ROOT}"
  StrCpy $R5 $UnTarget
  Call un.StripTrailingSlash
  StrCpy $UnTarget $R5
  StrCmp $UnSpkDataDir "" unSecCanonicalGo
  StrCpy $R5 $UnTarget
  StrCpy $R6 $UnSpkDataDir
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
  StrCmp $UnSpkDataDir "" unSecInstallDataGo
  StrCpy $R5 $UnTarget
  StrCpy $R6 $UnSpkDataDir
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
  StrCmp $UnSpkDataDir "" unSecInternalDataGo
  StrCpy $R5 $UnTarget
  StrCpy $R6 $UnSpkDataDir
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
  FindWindow $R0 "SopeekInstaller" ""
  StrCmp $R0 0 unSecDeleteTerminal
unSecUiTick:
  Sleep ${SPK_UNINSTALL_POLL_MS}
  IntOp $0 $0 + ${SPK_UNINSTALL_POLL_MS}
  IntCmp $0 ${SPK_UNINSTALL_UI_DONE_TIMEOUT_MS} 0 0 unSecUiTimeout
  Goto unSecUiWaitLoop
unSecUiDone:
  StrCmp $UnUiProcess 0 unSecUiDoneFind
  System::Call 'kernel32::WaitForSingleObject(p $UnUiProcess, i ${SPK_UNINSTALL_UI_PROCESS_WAIT_MS}) i .r1'
  StrCmp $1 0 unSecDeleteTerminal
  Goto unSecUiTimeout
unSecUiDoneFind:
  StrCpy $0 0
unSecUiDoneFindLoop:
  FindWindow $R0 "SopeekInstaller" ""
  StrCmp $R0 0 unSecDeleteTerminal
  Sleep ${SPK_UNINSTALL_POLL_MS}
  IntOp $0 $0 + ${SPK_UNINSTALL_POLL_MS}
  IntCmp $0 ${SPK_UNINSTALL_UI_PROCESS_WAIT_MS} 0 0 unSecUiTimeout
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
