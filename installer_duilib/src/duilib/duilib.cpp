#include "duilib.h"
#include <windows.h>

namespace duilib {
void Label::Paint(HDC dc) {
    HFONT f = CreateFontW(-fontSize,0,0,0,bold?FW_SEMIBOLD:FW_NORMAL,FALSE,FALSE,FALSE,DEFAULT_CHARSET,0,0,CLEARTYPE_QUALITY,0,L"Segoe UI");
    auto old=(HFONT)SelectObject(dc,f); SetBkMode(dc,TRANSPARENT); SetTextColor(dc,color); DrawTextW(dc,text.c_str(),-1,&bounds,DT_LEFT|DT_TOP|DT_WORDBREAK); SelectObject(dc,old); DeleteObject(f);
}
void Button::Paint(HDC dc) { HBRUSH b=CreateSolidBrush(primary?RGB(0,103,192):RGB(255,255,255)); FillRect(dc,&bounds,b); DeleteObject(b); Label label; label.bounds=bounds; label.text=text; label.fontSize=12; label.bold=true; label.color=primary?RGB(255,255,255):RGB(28,28,28); label.Paint(dc); }
bool Button::Hit(POINT p) const {return visible&&p.x>=bounds.left&&p.x<=bounds.right&&p.y>=bounds.top&&p.y<=bounds.bottom;}
void ProgressBar::Paint(HDC dc) { HBRUSH b=CreateSolidBrush(RGB(228,228,228)); FillRect(dc,&bounds,b); DeleteObject(b); RECT f=bounds; f.right=f.left+(f.right-f.left)*percent/100; b=CreateSolidBrush(RGB(0,103,192)); FillRect(dc,&f,b); DeleteObject(b); }
std::vector<Control*> XmlLayout::BuildDefaultControls() { return {}; }
}
