/* FAF-Launcher -- FreeAssetFilter discrete-GPU-enforcing tiny launcher.
 *
 * W1 (performance-ceiling-optimization, todo 10): on hybrid-graphics
 * machines the NVIDIA Optimus / AMD PowerXpress driver decides the adapter
 * by scanning the *PE export table* of the process image for
 *   - NvOptimusEnablement = 1
 *   - AmdPowerXpressRequestHighPerformance = 1
 * A ctypes global inside python.exe can never be an export, so the two
 * DWORDs must live in (and be exported from) this launcher EXE. The driver
 * keys off the launcher image; the child python process inherits the
 * high-performance adapter selection.
 *
 * Semantics:
 *   - Zero UI: built with /SUBSYSTEM:WINDOWS, creates no window, spawns
 *     the child with CREATE_NO_WINDOW, never touches GPU/D3D itself.
 *   - Spawns the real app via CreateProcessW (NOT system()/cmd.exe):
 *     default target is `python -m freeassetfilter.app.main` resolved
 *     against the project root (parent dir of this EXE, walked up until
 *     freeassetfilter/app/main.py is found). Extra launcher argv are
 *     forwarded verbatim to the child.
 *   - Test override: env FAF_LAUNCHER_CMD, when non-empty, is used as the
 *     full child command line instead (lets QA prove exit-code
 *     propagation without booting the GUI).
 *   - Waits (WaitForSingleObject) and propagates the child exit code.
 *
 * Build (MSVC, from repo root):
 *   launcher\\build_launcher.ps1
 * or directly:
 *   cl launcher\\launcher.c launcher\\launcher.def /O2 /nologo ^
 *      /Fe:launcher\\FAF-Launcher.exe /link /SUBSYSTEM:WINDOWS
 *
 * Verify:
 *   dumpbin /exports launcher\\FAF-Launcher.exe   (must list BOTH names)
 */

#define WIN32_LEAN_AND_MEAN
#ifndef UNICODE
#define UNICODE
#endif
#include <windows.h>
#include <shellapi.h>
#include <stdio.h>
#include <string.h>

/* ---- W1 GPU exports (PE export table of this EXE image) ---- */
__declspec(dllexport) DWORD NvOptimusEnablement = 1;
__declspec(dllexport) DWORD AmdPowerXpressRequestHighPerformance = 1;

/* Keep the exports referenced so no linker GC pass can drop them. */
static DWORD keep_gpu_exports_alive(void) {
    volatile DWORD keep =
        NvOptimusEnablement + AmdPowerXpressRequestHighPerformance;
    return (DWORD)keep;
}

#define CMDLINE_CAP 32768

/* Append one argv element with Win32 quoting rules. */
static BOOL append_quoted(
    wchar_t *dst, size_t cap, size_t *len, const wchar_t *arg) {
    size_t i, bs;
    BOOL need_quote = (arg[0] == L'\0');
    for (i = 0; arg[i] != L'\0'; i++) {
        if (arg[i] == L' ' || arg[i] == L'\t' || arg[i] == L'"') {
            need_quote = TRUE;
            break;
        }
    }
    if (need_quote) {
        if (*len + 1 >= cap) return FALSE;
        dst[(*len)++] = L'"';
    }
    for (i = 0, bs = 0; ; i++) {
        wchar_t c = arg[i];
        if (c == L'\\') {
            bs++;
        } else if (c == L'"') {
            /* Escape pending backslashes (doubled) + the quote. */
            size_t k;
            for (k = 0; k < bs * 2 + 1; k++) {
                if (*len + 1 >= cap) return FALSE;
                dst[(*len)++] = L'\\';
            }
            if (*len + 1 >= cap) return FALSE;
            dst[(*len)++] = L'"';
            bs = 0;
        } else {
            size_t k;
            for (k = 0; k < bs; k++) {
                if (*len + 1 >= cap) return FALSE;
                dst[(*len)++] = L'\\';
            }
            bs = 0;
            if (c == L'\0') break;
            if (*len + 1 >= cap) return FALSE;
            dst[(*len)++] = c;
        }
    }
    if (need_quote) {
        if (*len + 1 >= cap) return FALSE;
        dst[(*len)++] = L'"';
    }
    if (*len + 1 >= cap) return FALSE;
    dst[*len] = L'\0';
    return TRUE;
}

/* Walk exe_dir upward (<=3 levels) for freeassetfilter/app/main.py. */
static BOOL find_project_root(const wchar_t *exe_dir,
                              wchar_t *root, DWORD root_cap) {
    static const wchar_t *marker =
        L"freeassetfilter\\app\\main.py";
    wchar_t cur[MAX_PATH];
    int up;
    size_t n = wcslen(exe_dir);
    if (n + 1 > MAX_PATH) return FALSE;
    wcscpy_s(cur, MAX_PATH, exe_dir);
    for (up = 0; up <= 3; up++) {
        wchar_t probe[MAX_PATH];
        _snwprintf_s(probe, MAX_PATH, _TRUNCATE, L"%s\\%s", cur, marker);
        if (GetFileAttributesW(probe) != INVALID_FILE_ATTRIBUTES) {
            wcsncpy_s(root, root_cap, cur, _TRUNCATE);
            return TRUE;
        }
        /* Strip one trailing component. */
        {
            wchar_t *sep = wcsrchr(cur, L'\\');
            if (sep == NULL || sep == cur) break;
            /* Don't strip a drive root like C:. */
            if (sep == cur + 2 && cur[1] == L':') break;
            *sep = L'\0';
        }
    }
    wcsncpy_s(root, root_cap, exe_dir, _TRUNCATE);
    return FALSE;
}

static BOOL file_exists(const wchar_t *path) {
    return GetFileAttributesW(path) != INVALID_FILE_ATTRIBUTES;
}

int WINAPI WinMain(HINSTANCE inst, HINSTANCE prev,
                   LPSTR cmd_ansi, int show) {
    wchar_t exe_path[MAX_PATH];
    wchar_t exe_dir[MAX_PATH];
    wchar_t root[MAX_PATH];
    wchar_t cmdline[CMDLINE_CAP];
    size_t cmdlen = 0;
    wchar_t *mutable_cmd = NULL;
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    DWORD child_code = 1;
    wchar_t *wargv = NULL;
    (void)inst;
    (void)prev;
    (void)cmd_ansi;
    (void)show;

    keep_gpu_exports_alive();

    if (!GetModuleFileNameW(NULL, exe_path, MAX_PATH)) return 1;
    {
        wchar_t *sep = wcsrchr(exe_path, L'\\');
        size_t dn = (sep != NULL) ? (size_t)(sep - exe_path) : 0;
        if (dn == 0 || dn >= MAX_PATH) return 1;
        wcsncpy_s(exe_dir, MAX_PATH, exe_path, dn);
    }
    find_project_root(exe_dir, root, MAX_PATH);

    /* Test/QA override: full child command line from the environment. */
    {
        DWORD need = GetEnvironmentVariableW(L"FAF_LAUNCHER_CMD", NULL, 0);
        if (need > 1 && need <= CMDLINE_CAP) {
            static wchar_t override_cmd[CMDLINE_CAP];
            GetEnvironmentVariableW(
                L"FAF_LAUNCHER_CMD", override_cmd, CMDLINE_CAP);
            wcsncpy_s(cmdline, CMDLINE_CAP, override_cmd, _TRUNCATE);
            goto spawn;
        }
    }

    /* Default target: <python> -m freeassetfilter.app.main [fwd args]. */
    {
        wchar_t python[MAX_PATH];
        wchar_t venv_py[MAX_PATH];
        int i, argc = 0;
        LPWSTR *argv = NULL;

        /* 1) explicit env, 2) repo .venv, 3) PATH `python`. */
        if (GetEnvironmentVariableW(
                L"FAF_PYTHON", python, MAX_PATH) > 0) {
            /* use as-is */
        } else {
            _snwprintf_s(venv_py, MAX_PATH, _TRUNCATE,
                         L"%s\\.venv\\Scripts\\python.exe", root);
            if (file_exists(venv_py)) {
                wcsncpy_s(python, MAX_PATH, venv_py, _TRUNCATE);
            } else {
                wcsncpy_s(python, MAX_PATH, L"python", _TRUNCATE);
            }
        }
        if (!append_quoted(cmdline, CMDLINE_CAP, &cmdlen, python))
            return 1;
        {
            static const wchar_t *fixed_args[] = {
                L"-m", L"freeassetfilter.app.main"
            };
            for (i = 0; i < 2; i++) {
                if (cmdlen + 1 >= CMDLINE_CAP) return 1;
                cmdline[cmdlen++] = L' ';
                cmdline[cmdlen] = L'\0';
                if (!append_quoted(
                        cmdline, CMDLINE_CAP, &cmdlen, fixed_args[i]))
                    return 1;
            }
        }
        /* Forward launcher argv[1..] verbatim. */
        argv = CommandLineToArgvW(GetCommandLineW(), &argc);
        if (argv != NULL) {
            for (i = 1; i < argc; i++) {
                if (cmdlen + 1 >= CMDLINE_CAP) break;
                cmdline[cmdlen++] = L' ';
                cmdline[cmdlen] = L'\0';
                if (!append_quoted(cmdline, CMDLINE_CAP, &cmdlen, argv[i]))
                    break;
            }
            LocalFree(argv);
        }
        wargv = NULL;
    }

spawn:
    mutable_cmd = (wchar_t *)HeapAlloc(
        GetProcessHeap(), 0, CMDLINE_CAP * sizeof(wchar_t));
    if (mutable_cmd == NULL) return 1;
    wcsncpy_s(mutable_cmd, CMDLINE_CAP, cmdline, _TRUNCATE);

    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));
    if (!CreateProcessW(NULL, mutable_cmd,
                        NULL, NULL, FALSE,
                        CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT,
                        NULL, root, &si, &pi)) {
        DWORD err = GetLastError();
        wchar_t msg[512];
        _snwprintf_s(msg, 512, _TRUNCATE,
                     L"FAF-Launcher: failed to start child process "
                     L"(error %lu).\nCommand: %.380s",
                     err, mutable_cmd);
        MessageBoxW(NULL, msg, L"FAF-Launcher", MB_OK | MB_ICONERROR);
        HeapFree(GetProcessHeap(), 0, mutable_cmd);
        return 1;
    }
    HeapFree(GetProcessHeap(), 0, mutable_cmd);
    WaitForSingleObject(pi.hProcess, INFINITE);
    if (!GetExitCodeProcess(pi.hProcess, &child_code)) child_code = 1;
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    if (child_code == STILL_ACTIVE) child_code = 1;
    return (int)child_code;
}
