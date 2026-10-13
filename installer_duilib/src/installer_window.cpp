#include "installer_window.h"
#include <windows.h>
#include <commctrl.h>
#include <shlobj.h>
#include <filesystem>
#include <algorithm>

namespace fs = std::filesystem;
static constexpr UINT WM_INSTALL_PROGRESS = WM_APP + 1;
static constexpr UINT WM_INSTALL_DONE = WM_APP + 2;
static constexpr UINT WM_UI_ANIMATE = WM_APP + 3;
static constexpr COLORREF BG = RGB(235,245,255), PANEL = RGB(255,255,255), NAV = RGB(239,247,255), NAV_MUTED = RGB(157,176,198), BLUE = RGB(31,125,232), BLUE_DARK = RGB(23,93,181), TEXT = RGB(37,48,63), MUTED = RGB(108,126,148), BORDER = RGB(218,231,244);

InstallerWindow::InstallerWindow(HINSTANCE instance, std::wstring payload, std::wstring resultPath) : instance_(instance), payload_(std::move(payload)), resultPath_(std::move(resultPath)) {
    installDir_ = L"C:\\Program Files\\FreeAssetFilter";
}

int InstallerWindow::Run() {
    SetProcessDPIAware();
    HDC screen = GetDC(nullptr);
    dpi_ = GetDeviceCaps(screen, LOGPIXELSX);
    ReleaseDC(nullptr, screen);
    windowWidth_ = MulDiv(720, dpi_, 96);
    windowHeight_ = MulDiv(480, dpi_, 96);
    INITCOMMONCONTROLSEX ic{sizeof(ic), ICC_PROGRESS_CLASS}; InitCommonControlsEx(&ic);
    WNDCLASSW wc{}; wc.hInstance=instance_; wc.lpfnWndProc=WindowProc; wc.lpszClassName=L"FreeAssetFilterInstaller";
    wc.hCursor=LoadCursor(nullptr, IDC_ARROW); wc.hbrBackground=nullptr; wc.hIcon=LoadIconW(instance_, MAKEINTRESOURCEW(1)); RegisterClassW(&wc);
    RECT work{}; SystemParametersInfoW(SPI_GETWORKAREA,0,&work,0);
    int left=work.left+(work.right-work.left-windowWidth_)/2;
    int top=work.top+(work.bottom-work.top-windowHeight_)/2;
    int workLeft=static_cast<int>(work.left), workTop=static_cast<int>(work.top);
    int workRight=static_cast<int>(work.right), workBottom=static_cast<int>(work.bottom);
    left=std::max(workLeft,std::min(left,workRight-windowWidth_));
    top=std::max(workTop,std::min(top,workBottom-windowHeight_));
    window_=CreateWindowExW(WS_EX_APPWINDOW,wc.lpszClassName,L"FreeAssetFilter 安装程序",WS_POPUP,
        left,top,windowWidth_,windowHeight_,nullptr,nullptr,instance_,this);
    SetWindowRgn(window_,CreateRoundRectRgn(0,0,windowWidth_,windowHeight_,S(16),S(16)),TRUE);
    ShowWindow(window_,SW_SHOW); UpdateWindow(window_); Layout();
    animationTimer_ = SetTimer(window_, 1, 16, nullptr);
    MSG msg{}; while(GetMessageW(&msg,nullptr,0,0)>0){TranslateMessage(&msg);DispatchMessageW(&msg);} return (int)msg.wParam;
}

LRESULT CALLBACK InstallerWindow::WindowProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp){
    auto* self=reinterpret_cast<InstallerWindow*>(GetWindowLongPtrW(hwnd,GWLP_USERDATA));
    if(msg==WM_NCCREATE){self=(InstallerWindow*)((CREATESTRUCTW*)lp)->lpCreateParams; SetWindowLongPtrW(hwnd,GWLP_USERDATA,(LONG_PTR)self); self->window_=hwnd;}
    return self ? self->HandleMessage(msg,wp,lp) : DefWindowProcW(hwnd,msg,wp,lp);
}

void InstallerWindow::DrawTextLine(HDC dc,const std::wstring& text,RECT r,int size,COLORREF color,bool bold,UINT flags){
    // The reference layout uses CSS pixels, not point sizes. Scale px by the actual monitor DPI once.
    int pixelSize = size;
    HFONT f=CreateFontW(-pixelSize,0,0,0,bold?FW_SEMIBOLD:FW_NORMAL,FALSE,FALSE,FALSE,DEFAULT_CHARSET,OUT_DEFAULT_PRECIS,CLIP_DEFAULT_PRECIS,CLEARTYPE_QUALITY,DEFAULT_PITCH,L"Segoe UI");
    auto old=(HFONT)SelectObject(dc,f); SetTextColor(dc,color); SetBkMode(dc,TRANSPARENT); DrawTextW(dc,text.c_str(),-1,&r,flags); SelectObject(dc,old); DeleteObject(f);
}

void InstallerWindow::Paint(HDC dc){
    int saved = SaveDC(dc);
    SetMapMode(dc, MM_ANISOTROPIC);
    SetWindowExtEx(dc, 720, 480, nullptr);
    SetViewportExtEx(dc, windowWidth_, windowHeight_, nullptr);
    RECT client{0, 0, 720, 480};
    HBRUSH bg=CreateSolidBrush(BG); FillRect(dc,&client,bg); DeleteObject(bg);
    RECT nav{0,0,190,480}; HBRUSH navBrush=CreateSolidBrush(NAV); FillRect(dc,&nav,navBrush); DeleteObject(navBrush);
    // Soft blue brand shapes reproduce the reference glass-like background without external assets.
    HPEN noPen=CreatePen(PS_NULL,0,0); auto savedPen=(HPEN)SelectObject(dc,noPen);
    HBRUSH glow=CreateSolidBrush(RGB(220,239,255)); auto glowOld=(HBRUSH)SelectObject(dc,glow); Ellipse(dc,90,318,280,540); SelectObject(dc,glowOld); DeleteObject(glow);
    HBRUSH logo=CreateSolidBrush(BLUE); auto logoOld=(HBRUSH)SelectObject(dc,logo); RoundRect(dc,24,24,58,58,9,9); SelectObject(dc,logoOld); DeleteObject(logo);
    DrawTextLine(dc,L"◆",{24,24,58,58},16,RGB(255,255,255),false,DT_CENTER|DT_VCENTER|DT_SINGLELINE);
    DrawTextLine(dc,L"FreeAssetFilter 安装向导",{70,25,184,58},10,TEXT,true,DT_LEFT|DT_VCENTER|DT_WORDBREAK);
    const wchar_t* steps[]={L"欢迎",L"许可协议",L"安装位置",L"安装进度",L"完成"};
    for(int i=0;i<5;i++){int y=106+i*43; COLORREF dotColor=i<=page_?BLUE:RGB(207,220,234); HBRUSH dot=CreateSolidBrush(dotColor); auto dotOld=(HBRUSH)SelectObject(dc,dot); Ellipse(dc,27,y,43,y+16); SelectObject(dc,dotOld); DeleteObject(dot); if(i<4){HPEN p=CreatePen(PS_SOLID,1,i<page_?BLUE:RGB(207,220,234));auto op=(HPEN)SelectObject(dc,p);MoveToEx(dc,35,y+16,nullptr);LineTo(dc,35,y+43);SelectObject(dc,op);DeleteObject(p);} DrawTextLine(dc,steps[i],{58,y-3,170,y+20},11,i==page_?BLUE:MUTED,i==page_,DT_LEFT|DT_VCENTER|DT_SINGLELINE);}
    DrawTextLine(dc,L"1. 欢迎",{18,446,174,468},10,MUTED,false,DT_LEFT|DT_VCENTER|DT_SINGLELINE);
    DrawTextLine(dc,L"v1.0.0-alpha.5",{28,446,174,468},10,NAV_MUTED,false,DT_LEFT|DT_VCENTER|DT_SINGLELINE);
    RECT main{190,0,720,416}; HBRUSH panel=CreateSolidBrush(PANEL); FillRect(dc,&main,panel); DeleteObject(panel);
    // Pale blue decorative waves at the right edge, matching the reference composition.
    HBRUSH wave=CreateSolidBrush(RGB(242,249,255)); auto waveOld=(HBRUSH)SelectObject(dc,wave); Ellipse(dc,585,40,760,220); Ellipse(dc,635,270,760,416); SelectObject(dc,waveOld); DeleteObject(wave); SelectObject(dc,savedPen); DeleteObject(noPen);
    int ox=animationOffset_;
    if(page_==0){
        HBRUSH appIcon=CreateSolidBrush(BLUE); auto appOld=(HBRUSH)SelectObject(dc,appIcon); RoundRect(dc,258+ox,58,338+ox,138,18,18); SelectObject(dc,appOld); DeleteObject(appIcon); DrawTextLine(dc,L"◆",{258+ox,58,338+ox,138},32,RGB(255,255,255),false,DT_CENTER|DT_VCENTER|DT_SINGLELINE);
        DrawTextLine(dc,L"FreeAssetFilter",{238+ox,160,680+ox,194},24,TEXT,true,DT_LEFT|DT_VCENTER|DT_SINGLELINE); DrawTextLine(dc,L"免费 · 开源 · 高效的素材过滤工具",{238+ox,202,680+ox,226},12,MUTED,false,DT_LEFT|DT_VCENTER|DT_SINGLELINE); DrawTextLine(dc,L"本安装向导将引导您完成 FreeAssetFilter 的安装过程。\n该项目旨在帮助您快速浏览、管理和过滤各类素材资源。",{238+ox,266,650+ox,318},12,MUTED,false,DT_LEFT|DT_TOP|DT_WORDBREAK);
    } else if(page_==1){
        DrawTextLine(dc,L"许可协议",{238+ox,62,680+ox,96},22,TEXT,true); DrawTextLine(dc,L"请仔细阅读以下条款。你必须接受本协议才能继续安装。",{238+ox,104,680+ox,130},12,MUTED);
        RECT box{238+ox,150,680+ox,330}; HBRUSH b=CreateSolidBrush(RGB(250,252,255)); FillRect(dc,&box,b); DeleteObject(b); HPEN border=CreatePen(PS_SOLID,1,BORDER); auto oldPen=(HPEN)SelectObject(dc,border); Rectangle(dc,box.left,box.top,box.right,box.bottom); SelectObject(dc,oldPen); DeleteObject(border); DrawTextLine(dc,L"GNU General Public License v3.0\n\nThis program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation.\n\n本软件依据 GNU Affero General Public License v3 授权。",{258+ox,166,660+ox,310},11,TEXT);
        agreeRect_={238+ox,348,520+ox,374}; DrawTextLine(dc,(agreed_?L"☑ ":L"☐ ")+std::wstring(L"我已阅读并同意上述许可协议"),agreeRect_,12,TEXT,false,DT_LEFT|DT_VCENTER|DT_SINGLELINE);
    } else if(page_==2){
        DrawTextLine(dc,L"选择安装位置",{238+ox,62,680+ox,96},22,TEXT,true); DrawTextLine(dc,L"请选择 FreeAssetFilter 的安装目录。",{238+ox,104,680+ox,130},12,MUTED);
        DrawTextLine(dc,L"安装目录",{238+ox,158,680+ox,180},11,TEXT,true); RECT path{238+ox,188,580+ox,222}; HBRUSH p=CreateSolidBrush(RGB(250,251,253)); FillRect(dc,&path,p); DeleteObject(p); DrawTextLine(dc,installDir_,{250+ox,194,568+ox,216},11,TEXT,false,DT_LEFT|DT_VCENTER|DT_SINGLELINE); browseRect_={590+ox,188,680+ox,222}; DrawTextLine(dc,L"浏览",browseRect_,11,BLUE_DARK,true,DT_CENTER|DT_VCENTER|DT_SINGLELINE); DrawTextLine(dc,L"所需空间 486 MB",{238+ox,240,430+ox,264},11,MUTED); desktopRect_={238+ox,270,500+ox,294}; DrawTextLine(dc,(desktopShortcut_?L"☑ ":L"☐ ")+std::wstring(L"创建桌面快捷方式"),desktopRect_,12,TEXT,false,DT_LEFT|DT_VCENTER|DT_SINGLELINE); DrawTextLine(dc,L"☑  创建开始菜单文件夹",{238+ox,300,500+ox,324},12,TEXT,false,DT_LEFT|DT_VCENTER|DT_SINGLELINE); DrawTextLine(dc,L"☐  开机时自动启动",{238+ox,330,500+ox,354},12,TEXT,false,DT_LEFT|DT_VCENTER|DT_SINGLELINE);
    } else if(page_==3){
        DrawTextLine(dc,L"正在安装",{238+ox,62,680+ox,96},22,TEXT,true); DrawTextLine(dc,L"正在安装 FreeAssetFilter，请稍候...",{238+ox,104,680+ox,130},12,MUTED); RECT track{238+ox,170,680+ox,178}; HBRUSH t=CreateSolidBrush(RGB(225,235,246)); FillRect(dc,&track,t); DeleteObject(t); RECT fill=track; fill.right=fill.left+(fill.right-fill.left)*progress_/100; HBRUSH f=CreateSolidBrush(BLUE); FillRect(dc,&fill,f); DeleteObject(f); DrawTextLine(dc,std::to_wstring(progress_)+L"%",{638+ox,144,680+ox,166},11,MUTED,true,DT_RIGHT|DT_VCENTER|DT_SINGLELINE); DrawTextLine(dc,L"正在复制文件...",{238+ox,194,660+ox,220},11,MUTED); DrawTextLine(dc,L"✓  初始化安装环境\n✓  复制文件\n◉  安装组件\n○  完成安装",{258+ox,250,650+ox,340},12,MUTED);
    } else {
        HBRUSH done=CreateSolidBrush(BLUE); auto doneOld=(HBRUSH)SelectObject(dc,done); Ellipse(dc,390+ox,70,470+ox,150); SelectObject(dc,doneOld); DeleteObject(done); DrawTextLine(dc,L"✓",{390+ox,70,470+ox,150},36,RGB(255,255,255),false,DT_CENTER|DT_VCENTER|DT_SINGLELINE); DrawTextLine(dc,L"安装完成",{238+ox,174,680+ox,210},24,TEXT,true,DT_CENTER|DT_VCENTER|DT_SINGLELINE); DrawTextLine(dc,L"FreeAssetFilter 已成功安装到您的电脑。",{238+ox,220,680+ox,248},12,MUTED,false,DT_CENTER|DT_VCENTER|DT_SINGLELINE); launchRect_={350+ox,280,570+ox,306}; DrawTextLine(dc,(launch_?L"☑ ":L"☐ ")+std::wstring(L"立即启动 FreeAssetFilter"),launchRect_,12,TEXT,false,DT_CENTER|DT_VCENTER|DT_SINGLELINE);
    }
    HBRUSH footer=CreateSolidBrush(RGB(249,252,255)); RECT foot{190,416,720,480}; FillRect(dc,&foot,footer); DeleteObject(footer); Layout(); DrawTextLine(dc,(page_==0?L"取消":L"上一步"),backRect_,12,MUTED,false,DT_CENTER|DT_VCENTER|DT_SINGLELINE); HBRUSH primary=CreateSolidBrush(BLUE); auto old=(HBRUSH)SelectObject(dc,primary); RoundRect(dc,nextRect_.left,nextRect_.top,nextRect_.right,nextRect_.bottom,5,5); SelectObject(dc,old); DeleteObject(primary); DrawTextLine(dc,(page_==3?L"安装中...":page_==4?L"完成":page_==2?L"下一步":L"下一步"),nextRect_,12,RGB(255,255,255),true,DT_CENTER|DT_VCENTER|DT_SINGLELINE);
    RestoreDC(dc, saved);
}

void InstallerWindow::Layout(){backRect_={512,434,608,466}; nextRect_={616,434,712,466};}
bool InstallerWindow::Hit(RECT r,POINT p)const{
    POINT logical{MulDiv(p.x,720,windowWidth_),MulDiv(p.y,480,windowHeight_)};
    return logical.x>=r.left&&logical.x<=r.right&&logical.y>=r.top&&logical.y<=r.bottom;
}
int InstallerWindow::S(int value) const { return MulDiv(value,dpi_,96); }
void InstallerWindow::SetPage(int p){page_=p;animationTick_=0;animationOffset_=18;InvalidateRect(window_,nullptr,TRUE);}

LRESULT InstallerWindow::HandleMessage(UINT msg,WPARAM wp,LPARAM lp){
    if(msg==WM_ERASEBKGND){return 1;}
    if(msg==WM_PAINT){
        PAINTSTRUCT ps; HDC screen=BeginPaint(window_,&ps);
        RECT client; GetClientRect(window_,&client); int width=client.right, height=client.bottom;
        HDC memory=CreateCompatibleDC(screen); HBITMAP bitmap=CreateCompatibleBitmap(screen,width,height); HGDIOBJ old=SelectObject(memory,bitmap);
        Paint(memory);
        // Copy the complete back buffer. Partial blits mix physical-DPI regions during page animation.
        BitBlt(screen,0,0,width,height,memory,0,0,SRCCOPY);
        SelectObject(memory,old); DeleteObject(bitmap); DeleteDC(memory); EndPaint(window_,&ps); return 0;
    }
    if(msg==WM_TIMER){
        if(animationOffset_>0){animationOffset_=std::max(0,animationOffset_-3); InvalidateRect(window_,nullptr,FALSE);}
        return 0;
    }
    if(msg==WM_CLOSE){if(!installing_) WriteCancelResult(); if(animationTimer_)KillTimer(window_,animationTimer_);DestroyWindow(window_);return 0;} if(msg==WM_DESTROY){if(animationTimer_)KillTimer(window_,animationTimer_);PostQuitMessage(0);return 0;}
    if(msg==WM_NCHITTEST){POINT p{(LONG)(short)LOWORD(lp),(LONG)(short)HIWORD(lp)};ScreenToClient(window_,&p);POINT logical{MulDiv(p.x,720,windowWidth_),MulDiv(p.y,480,windowHeight_)};if(logical.y<40&&logical.x<632)return HTCAPTION;return HTCLIENT;}
    if(msg==WM_LBUTTONDOWN){POINT p{(LONG)(short)LOWORD(lp),(LONG)(short)HIWORD(lp)}; if(p.y<40&&p.x>=632&&p.x<676){ShowWindow(window_,SW_MINIMIZE);return 0;} if(p.y<40&&p.x>=676){DestroyWindow(window_);return 0;} if(Hit(agreeRect_,p)){agreed_=!agreed_;InvalidateRect(window_,nullptr,TRUE);} else if(Hit(desktopRect_,p)){desktopShortcut_=!desktopShortcut_;InvalidateRect(window_,nullptr,TRUE);} else if(Hit(launchRect_,p)){launch_=!launch_;InvalidateRect(window_,nullptr,TRUE);} else if(Hit(browseRect_,p)){Browse();} else if(Hit(backRect_,p)){if(page_==0)DestroyWindow(window_);else if(page_>0&&!installing_)SetPage(page_-1);} else if(Hit(nextRect_,p)&&!installing_){if(page_==0)SetPage(1);else if(page_==1&&agreed_)SetPage(2);else if(page_==2)StartInstall();else if(page_==4){if(launch_)ShellExecuteW(nullptr,L"open",(installDir_+L"\\FreeAssetFilter.exe").c_str(),nullptr,nullptr,SW_SHOWNORMAL);DestroyWindow(window_);}} return 0;}
    if(msg==WM_INSTALL_PROGRESS){progress_=(int)wp;InvalidateRect(window_,nullptr,FALSE);return 0;} if(msg==WM_INSTALL_DONE){installing_=false;SetPage(4);return 0;}
    return DefWindowProcW(window_,msg,wp,lp);
}

void InstallerWindow::Browse(){BROWSEINFOW bi{}; bi.hwndOwner=window_; bi.lpszTitle=L"选择 FreeAssetFilter 安装目录"; LPITEMIDLIST id=SHBrowseForFolderW(&bi); if(id){wchar_t path[MAX_PATH];if(SHGetPathFromIDListW(id,path))installDir_=path;CoTaskMemFree(id);InvalidateRect(window_,nullptr,TRUE);}}
void InstallerWindow::AddFiles(const std::wstring& folder){for(auto& e:fs::recursive_directory_iterator(folder))if(e.is_regular_file())files_.push_back(e.path().wstring());}
bool InstallerWindow::CopyTree(const std::wstring& source,const std::wstring& target){try{fs::create_directories(target);for(auto& e:fs::recursive_directory_iterator(source)){auto rel=fs::relative(e.path(),source);auto out=fs::path(target)/rel;if(e.is_directory())fs::create_directories(out);else fs::copy_file(e.path(),out,fs::copy_options::overwrite_existing);}return true;}catch(...){return false;}}
DWORD WINAPI InstallerWindow::InstallThreadProc(LPVOID p){((InstallerWindow*)p)->InstallThread();return 0;}
void InstallerWindow::WriteCancelResult(){
    HANDLE file=CreateFileW(resultPath_.c_str(),GENERIC_WRITE,0,nullptr,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,nullptr);
    if(file!=INVALID_HANDLE_VALUE){DWORD bytes=0;const unsigned short bom=0xFEFF;const wchar_t cancel[]=L"CANCEL";WriteFile(file,&bom,sizeof(bom),&bytes,nullptr);WriteFile(file,cancel,sizeof(cancel)-sizeof(wchar_t),&bytes,nullptr);CloseHandle(file);}
}
void InstallerWindow::InstallThread(){
    for(int wait=0;wait<6000 && !fs::exists(fs::path(payload_)/L"FreeAssetFilter.exe");++wait) Sleep(100);
    if(!fs::exists(fs::path(payload_)/L"FreeAssetFilter.exe")){WriteCancelResult();PostMessageW(window_,WM_INSTALL_DONE,0,0);return;}
    fs::create_directories(installDir_);
    bool ok=CopyTree(payload_,installDir_);
    if(ok){
        HANDLE file=CreateFileW(resultPath_.c_str(),GENERIC_WRITE,0,nullptr,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,nullptr);
        if(file!=INVALID_HANDLE_VALUE){DWORD bytes=0;const unsigned short bom=0xFEFF;WriteFile(file,&bom,sizeof(bom),&bytes,nullptr);WriteFile(file,installDir_.c_str(),(DWORD)(installDir_.size()*sizeof(wchar_t)),&bytes,nullptr);CloseHandle(file);}
    }
    for(int i=0;i<=100;i+=2){PostMessageW(window_,WM_INSTALL_PROGRESS,i,0);Sleep(18);}
    PostMessageW(window_,WM_INSTALL_DONE,ok?1:0,0);
}
void InstallerWindow::StartInstall(){installing_=true;SetPage(3);installThread_=CreateThread(nullptr,0,InstallThreadProc,this,0,nullptr);}
