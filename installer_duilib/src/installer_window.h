#pragma once
#include <windows.h>
#include <string>
#include <vector>

class InstallerWindow {
public:
    InstallerWindow(HINSTANCE instance, std::wstring payload, std::wstring resultPath);
    int Run();

private:
    static LRESULT CALLBACK WindowProc(HWND, UINT, WPARAM, LPARAM);
    LRESULT HandleMessage(UINT, WPARAM, LPARAM);
    void Paint(HDC);
    void Layout();
    void SetPage(int page);
    void StartInstall();
    void Browse();
    bool CopyTree(const std::wstring& source, const std::wstring& target);
    static DWORD WINAPI InstallThreadProc(LPVOID);
    void InstallThread();
    void WriteCancelResult();
    void AddFiles(const std::wstring& folder);
    void DrawTextLine(HDC, const std::wstring&, RECT, int, COLORREF, bool = false, UINT flags = DT_LEFT | DT_TOP | DT_WORDBREAK);
    bool Hit(RECT, POINT) const;
    int S(int value) const;

    HINSTANCE instance_{};
    HWND window_{};
    std::wstring payload_;
    std::wstring resultPath_;
    std::wstring installDir_;
    std::vector<std::wstring> files_;
    HANDLE installThread_{};
    int page_{0};
    int progress_{0};
    bool agreed_{false};
    bool desktopShortcut_{false};
    bool launch_{true};
    bool installing_{false};
    bool finished_{false};
    bool dragging_{false};
    POINT dragOrigin_{};
    RECT nextRect_{}, backRect_{}, browseRect_, agreeRect_{}, desktopRect_{}, launchRect_{};
    UINT_PTR animationTimer_{0};
    int animationOffset_{0};
    int animationTick_{0};
    int dpi_{96};
    int windowWidth_{720};
    int windowHeight_{480};
};
