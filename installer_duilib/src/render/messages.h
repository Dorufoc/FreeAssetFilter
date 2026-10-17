#pragma once
#include <windows.h>
// wParam carries progress in PERMILLE (0..1000), NOT 0..100.
constexpr UINT WM_INSTALL_PROGRESS = WM_APP + 1; // wParam = permille 0..1000
constexpr UINT WM_INSTALL_DONE     = WM_APP + 2; // wParam = result code
constexpr UINT WM_UI_TICK          = WM_APP + 3; // animation frame
