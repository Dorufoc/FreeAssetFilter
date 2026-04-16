#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；
2. 商业使用：需联系 qpdrfc123@gmail.com 获取书面授权；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

图标处理工具模块
"""

import os
import struct
import ctypes
from ctypes import windll, byref, create_unicode_buffer, sizeof
from ctypes.wintypes import (DWORD, MAX_PATH, HANDLE, UINT,
                           LPCWSTR, LPWSTR, BOOL, HICON)

# 导入日志模块
from freeassetfilter.utils.app_logger import info, debug, warning, error

# 定义Windows API常量
SHGFI_ICON = 0x000000100
SHGFI_LARGEICON = 0x000000000
SHGFI_SMALLICON = 0x000000001
SHGFI_USEFILEATTRIBUTES = 0x000000010
SHGFI_ICONLOCATION = 0x000001000
SHGFI_SYSICONINDEX = 0x000004000
SHGFI_LINKOVERLAY = 0x000008000
SHGFI_SELECTED = 0x000010000
SHGFI_OPENICON = 0x000000002
SHGFI_SHELLICONSIZE = 0x00000004
SHGFI_TYPENAME = 0x000000400
SHGFI_DISPLAYNAME = 0x000000200
SHGFI_PIDL = 0x000000008
SHGFI_ATTRIBUTES = 0x000000800
SHGFI_ADDOVERLAYS = 0x000002000
SHGFI_OVERLAYINDEX = 0x000004000

FILE_ATTRIBUTE_NORMAL = 0x00000080
FILE_ATTRIBUTE_DIRECTORY = 0x00000010

# 定义Windows API结构
class SHFILEINFOW(ctypes.Structure):
    _fields_ = [
        ("hIcon", HICON),
        ("iIcon", ctypes.c_int),
        ("dwAttributes", DWORD),
        ("szDisplayName", ctypes.c_wchar * MAX_PATH),
        ("szTypeName", ctypes.c_wchar * 80)
    ]

class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", DWORD),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8)
    ]

# 加载Windows DLL
shell32 = windll.shell32
user32 = windll.user32
ole32 = windll.ole32

# 定义Windows API函数
SHGetFileInfoW = shell32.SHGetFileInfoW
SHGetFileInfoW.argtypes = [LPCWSTR, DWORD, ctypes.POINTER(SHFILEINFOW), DWORD, UINT]
SHGetFileInfoW.restype = HANDLE

DestroyIcon = user32.DestroyIcon
DestroyIcon.argtypes = [HICON]
DestroyIcon.restype = BOOL

SHGetKnownFolderPath = shell32.SHGetKnownFolderPath
SHGetKnownFolderPath.argtypes = [ctypes.POINTER(GUID), DWORD, HANDLE, ctypes.POINTER(ctypes.c_wchar_p)]
SHGetKnownFolderPath.restype = ctypes.c_long

CoTaskMemFree = ole32.CoTaskMemFree
CoTaskMemFree.argtypes = [ctypes.c_void_p]
CoTaskMemFree.restype = None

# IShellItemImageFactory 相关定义 - 用于获取高质量图标
SIIGBF_RESIZETOFIT = 0x00000000
SIIGBF_BIGGERSIZEOK = 0x00000001
SIIGBF_MEMORYONLY = 0x00000002
SIIGBF_ICONONLY = 0x00000004
SIIGBF_THUMBNAILONLY = 0x00000008
SIIGBF_INCACHEONLY = 0x00000010
SIIGBF_CROPTOSQUARE = 0x00000020
SIIGBF_WIDETHUMBNAILS = 0x00000040
SIIGBF_ICONBACKGROUND = 0x00000080
SIIGBF_SCALEUP = 0x00000100

# CLSID_ShellItem
CLSID_ShellItem = GUID(0x43826d1e, 0xe718, 0x42ee, (0xbc, 0x55, 0xa1, 0xe2, 0x61, 0xc3, 0x7b, 0xfe))

# IID_IShellItem
IID_IShellItem = GUID(0x43826d1e, 0xe718, 0x42ee, (0xbc, 0x55, 0xa1, 0xe2, 0x61, 0xc3, 0x7b, 0xfe))

# IID_IShellItemImageFactory
IID_IShellItemImageFactory = GUID(0xbcc18b79, 0xba16, 0x442f, (0x80, 0xc4, 0x8a, 0x59, 0xc5, 0x5c, 0x09, 0x7f))

# 解析lnk文件的函数
def get_lnk_target(lnk_path):
    """
    解析Windows快捷方式(.lnk)文件，获取其指向的目标文件路径
    """
    debug(f"解析LNK文件: {lnk_path}")
    try:
        # 定义必要的结构和常量
        class LNK_DATA(ctypes.Structure):
            _fields_ = [
                ("HeaderSize", DWORD),
                ("LinkCLSID", GUID),
                ("LinkFlags", DWORD),
                ("FileAttributes", DWORD),
                ("CreationTime", ctypes.c_ulonglong),
                ("AccessTime", ctypes.c_ulonglong),
                ("WriteTime", ctypes.c_ulonglong),
                ("FileSize", DWORD),
                ("IconIndex", DWORD),
                ("ShowCommand", DWORD),
                ("HotKey", ctypes.c_ushort),
                ("Reserved1", ctypes.c_ushort),
                ("Reserved2", ctypes.c_ushort),
                ("Reserved3", ctypes.c_ushort),
                ("LocalBasePath", ctypes.c_wchar * MAX_PATH),
            ]

        with open(lnk_path, 'rb') as f:
            # 读取LNK文件头
            header = f.read(76)
            if len(header) != 76:
                return None
            
            # 检查是否是有效的LNK文件
            if header[:4] != b'LNK\x00':
                return None
            
            # 获取LNK数据
            lnk_data = LNK_DATA.from_buffer_copy(header)
            
            # 检查是否有本地路径
            if lnk_data.LinkFlags & 0x01:  # HasLinkTargetIDList
                # 解析IDList格式（简化版本）
                f.seek(lnk_data.HeaderSize)
                id_list_size = struct.unpack('<H', f.read(2))[0]
                f.seek(f.tell() + id_list_size)
            
            # 读取本地路径
            if lnk_data.LinkFlags & 0x02:  # HasLinkInfo
                link_info_size = struct.unpack('<I', f.read(4))[0]
                f.seek(f.tell() + 12)  # Skip LinkInfoHeader
                local_base_path_offset = struct.unpack('<I', f.read(4))[0]
                f.seek(f.tell() + link_info_size - 16 + local_base_path_offset)
                
                # 读取以null结尾的宽字符串
                target_path = []
                while True:
                    char1 = f.read(1)
                    char2 = f.read(1)
                    if not char1 or not char2:
                        break
                    char_code = struct.unpack('<H', char1 + char2)[0]
                    if char_code == 0:
                        break
                    target_path.append(chr(char_code))
                
                target_path = ''.join(target_path)
                if target_path:
                    debug(f"LNK目标解析成功: {target_path}")
                    return target_path

        debug(f"LNK文件无有效目标路径: {lnk_path}")
        return None
    except (OSError, struct.error, ValueError) as e:
        debug(f"解析LNK文件失败: {lnk_path}, 错误: {e}")
        return None

# 定义ExtractIconEx函数
ExtractIconExW = shell32.ExtractIconExW
ExtractIconExW.argtypes = [LPCWSTR, ctypes.c_int, ctypes.POINTER(HICON), ctypes.POINTER(HICON), UINT]
ExtractIconExW.restype = UINT

def get_all_icons_from_exe(file_path):
    """
    从EXE文件中提取所有可用的图标

    参数:
        file_path: str - EXE文件路径

    返回:
        list - 包含所有图标信息的列表，每个元素是(dict):
            {"hicon": HICON, "index": int, "width": int, "height": int}
    """
    debug(f"提取EXE图标: {file_path}")
    icons = []

    try:
        # 获取图标数量
        icon_count = ExtractIconExW(file_path, -1, None, None, 0)
        debug(f"EXE文件包含图标数量: {icon_count}")

        if icon_count > 0:
            # 为图标信息获取定义必要的结构
            class ICONINFO(ctypes.Structure):
                _fields_ = [
                    ("fIcon", BOOL),
                    ("xHotspot", ctypes.c_uint),
                    ("yHotspot", ctypes.c_uint),
                    ("hbmMask", ctypes.c_void_p),
                    ("hbmColor", ctypes.c_void_p)
                ]
            
            class BITMAP(ctypes.Structure):
                _fields_ = [
                    ("bmType", DWORD),
                    ("bmWidth", DWORD),
                    ("bmHeight", DWORD),
                    ("bmWidthBytes", DWORD),
                    ("bmPlanes", ctypes.c_ushort),
                    ("bmBitsPixel", ctypes.c_ushort),
                    ("bmBits", ctypes.c_void_p)
                ]
            
            GetIconInfo = user32.GetIconInfo
            GetIconInfo.argtypes = [HICON, ctypes.POINTER(ICONINFO)]
            GetIconInfo.restype = BOOL
            
            GetObjectW = windll.gdi32.GetObjectW
            GetObjectW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
            GetObjectW.restype = ctypes.c_int
            
            DeleteObject = windll.gdi32.DeleteObject
            DeleteObject.argtypes = [ctypes.c_void_p]
            DeleteObject.restype = BOOL
            
            # 尝试使用SHDefExtractIcon获取不同尺寸的图标
            try:
                SHDefExtractIcon = shell32.SHDefExtractIconW
                SHDefExtractIcon.argtypes = [
                    LPCWSTR,  # pszIconFile
                    ctypes.c_int,  # iIndex
                    UINT,  # uFlags
                    ctypes.POINTER(HICON),  # phiconLarge
                    ctypes.POINTER(ctypes.c_uint),  # piconidLarge
                    UINT  # nIconSize
                ]
                SHDefExtractIcon.restype = ctypes.c_long
                
                # 尝试的图标尺寸（从高到低）
                icon_sizes = [1024, 512, 256, 128, 64, 32]  # 尝试更大的图标尺寸              
                for i in range(icon_count):
                    for size in icon_sizes:
                        hicon = HICON()
                        icon_id = ctypes.c_uint()
                        
                        # 提取指定索引和尺寸的图标
                        result = SHDefExtractIcon(
                            file_path,  # 图标文件路径
                            i,  # 图标索引
                            0,  # 标志
                            byref(hicon),  # 输出的图标句柄
                            byref(icon_id),  # 输出的图标ID
                            size  # 图标尺寸
                        )
                        
                        if result == 0 and hicon.value != 0:
                            # 获取图标尺寸
                            icon_info = ICONINFO()
                            if GetIconInfo(hicon, byref(icon_info)):
                                try:
                                    bmp = BITMAP()
                                    if GetObjectW(icon_info.hbmColor, sizeof(bmp), byref(bmp)) > 0:
                                        # 添加到图标列表
                                        icons.append({
                                            "hicon": hicon,
                                            "index": i,
                                            "width": bmp.bmWidth,
                                            "height": bmp.bmHeight
                                        })
                                        continue  # 保留当前图标句柄
                                finally:
                                    # 释放图标信息资源
                                    if icon_info.hbmMask:
                                        DeleteObject(icon_info.hbmMask)
                                    if icon_info.hbmColor:
                                        DeleteObject(icon_info.hbmColor)
                            
                            # 如果无法获取尺寸信息，释放图标
                            DestroyIcon(hicon)
            except (OSError, ctypes.WinError, AttributeError) as e:
                warning(f"SHDefExtractIcon提取图标失败: {file_path}, 错误: {e}")

            # 如果SHDefExtractIcon失败或返回空，使用ExtractIconEx作为备用
            if not icons:
                for i in range(icon_count):
                    # 为每个索引分别提取图标
                    large_icons = (HICON * 1)()
                    small_icons = (HICON * 1)()
                    
                    extracted_count = ExtractIconExW(file_path, i, byref(large_icons), byref(small_icons), 1)
                    
                    if extracted_count > 0:
                        # 处理大图标的情况
                        if large_icons[0]:
                            # 获取图标尺寸
                            icon_info = ICONINFO()
                            if GetIconInfo(large_icons[0], byref(icon_info)):
                                try:
                                    bmp = BITMAP()
                                    if GetObjectW(icon_info.hbmColor, sizeof(bmp), byref(bmp)) > 0:
                                        icons.append({
                                            "hicon": large_icons[0],
                                            "index": i,
                                            "width": bmp.bmWidth,
                                            "height": bmp.bmHeight
                                        })
                                        continue  # 保留当前图标句柄
                                finally:
                                    # 释放图标信息资源
                                    if icon_info.hbmMask:
                                        DeleteObject(icon_info.hbmMask)
                                    if icon_info.hbmColor:
                                        DeleteObject(icon_info.hbmColor)
                            
                            # 如果无法获取尺寸信息，释放图标
                            DestroyIcon(large_icons[0])
                        
                        # 处理小图标的情况
                        if small_icons[0]:
                            # 获取图标尺寸
                            icon_info = ICONINFO()
                            if GetIconInfo(small_icons[0], byref(icon_info)):
                                try:
                                    bmp = BITMAP()
                                    if GetObjectW(icon_info.hbmColor, sizeof(bmp), byref(bmp)) > 0:
                                        icons.append({
                                            "hicon": small_icons[0],
                                            "index": i,
                                            "width": bmp.bmWidth,
                                            "height": bmp.bmHeight
                                        })
                                        continue  # 保留当前图标句柄
                                finally:
                                    # 释放图标信息资源
                                    if icon_info.hbmMask:
                                        DeleteObject(icon_info.hbmMask)
                                    if icon_info.hbmColor:
                                        DeleteObject(icon_info.hbmColor)
                            
                            # 如果无法获取尺寸信息，释放图标
                            DestroyIcon(small_icons[0])

    except (OSError, ctypes.WinError) as e:
        warning(f"提取EXE图标失败: {file_path}, 错误: {e}")

    debug(f"提取到图标数量: {len(icons)}")
    return icons


def get_highest_resolution_icon(file_path, desired_size=256):
    """
    获取文件的最高分辨率图标，支持exe和lnk文件
    优先使用 IShellItemImageFactory (Windows资源管理器使用的接口) 获取高质量图标

    参数:
        file_path: str - 文件路径
        desired_size: int - 期望的图标大小（仅作为参考，实际会获取最高分辨率）

    返回:
        HICON - 图标句柄，如果获取失败则返回None
    """
    debug(f"获取高分辨率图标: {file_path}, 期望尺寸: {desired_size}")
    try:
        # 检查文件类型
        _, ext = os.path.splitext(file_path)
        ext = ext.lower()

        # 如果是lnk文件，获取其指向的目标文件
        target_path = None
        if ext == '.lnk':
            target_path = get_lnk_target(file_path)
            if target_path and os.path.exists(target_path):
                file_path = target_path
                _, ext = os.path.splitext(file_path)
                ext = ext.lower()

        # 首先尝试使用 IShellItemImageFactory 获取高质量图标（大尺寸）
        # 这是 Windows 资源管理器使用的接口，可以获取最佳质量的图标
        # 传入较大的尺寸（512）以获取最高分辨率
        hicon = get_icon_from_shell_item_image_factory(file_path, 512)
        if hicon:
            debug(f"通过IShellItemImageFactory获取图标成功: {file_path}")
            return hicon

        # 对于exe文件，使用get_all_icons_from_exe获取所有可用图标，然后选择最高分辨率的
        if ext == '.exe':
            debug(f"从EXE提取所有图标: {file_path}")
            # 获取所有可用图标
            all_icons = get_all_icons_from_exe(file_path)

            if all_icons:
                # 选择分辨率最高的图标
                best_icon = max(all_icons, key=lambda icon: icon["width"] * icon["height"])
                debug(f"选择最高分辨率图标: {best_icon['width']}x{best_icon['height']}")

                # 释放其他图标的句柄
                for icon in all_icons:
                    if icon["hicon"] != best_icon["hicon"]:
                        DestroyIcon(icon["hicon"])

                return best_icon["hicon"]
            debug(f"EXE文件未提取到图标: {file_path}")

        # 使用SHGetFileInfo获取其他类型文件的图标
        # 创建SHFILEINFO结构
        shfi = SHFILEINFOW()
        shfi_size = sizeof(shfi)

        # 使用SHGetFileInfo获取图标，移除SHGFI_SHELLICONSIZE以获取原始大小
        flags = SHGFI_ICON | SHGFI_USEFILEATTRIBUTES

        result = SHGetFileInfoW(
            file_path,
            FILE_ATTRIBUTE_NORMAL,
            byref(shfi),
            shfi_size,
            flags
        )

        if result == 0 or shfi.hIcon is None:
            # 尝试不带SHGFI_USEFILEATTRIBUTES的方式
            flags = SHGFI_ICON
            result = SHGetFileInfoW(
                file_path,
                0,
                byref(shfi),
                shfi_size,
                flags
            )

            if result == 0 or shfi.hIcon is None:
                debug(f"SHGetFileInfo获取图标失败: {file_path}")
                return None

        debug(f"通过SHGetFileInfo获取图标成功: {file_path}")
        return shfi.hIcon
    except (OSError, ctypes.WinError) as e:
        debug(f"获取高分辨率图标失败: {file_path}, 错误: {e}")
        return None

def get_icon_from_shell_item_image_factory(file_path, size=256):
    """
    使用 IShellItemImageFactory 获取高质量图标
    这是 Windows 资源管理器使用的接口，可以获取高质量、大尺寸的图标

    参数:
        file_path: str - 文件路径
        size: int - 期望的图标大小

    返回:
        HICON - 图标句柄，如果获取失败则返回None
    """
    debug(f"使用IShellItemImageFactory获取图标: {file_path}, 尺寸: {size}")
    try:
        # 定义必要的 COM 接口
        class IShellItemImageFactoryVtbl(ctypes.Structure):
            pass

        class IShellItemImageFactory(ctypes.Structure):
            pass

        # SHCreateItemFromParsingName 函数
        SHCreateItemFromParsingName = shell32.SHCreateItemFromParsingName
        SHCreateItemFromParsingName.argtypes = [
            LPCWSTR,  # pszPath
            ctypes.c_void_p,  # pbc
            ctypes.POINTER(GUID),  # riid
            ctypes.POINTER(ctypes.c_void_p)  # ppv
        ]
        SHCreateItemFromParsingName.restype = ctypes.c_long

        # 创建 ShellItem
        shell_item_ptr = ctypes.c_void_p()
        hr = SHCreateItemFromParsingName(
            file_path,
            None,
            byref(IID_IShellItemImageFactory),
            byref(shell_item_ptr)
        )

        if hr != 0 or not shell_item_ptr:
            return None

        try:
            # 将指针转换为 IShellItemImageFactory 接口
            # 使用 vtable 调用 GetImage 方法
            # vtable 布局: QueryInterface, AddRef, Release, GetImage

            # 获取 vtable 指针
            vtable_ptr = ctypes.cast(shell_item_ptr, ctypes.POINTER(ctypes.c_void_p)).contents.value
            if not vtable_ptr:
                return None

            # GetImage 是第4个函数 (索引3)
            get_image_ptr = ctypes.cast(vtable_ptr + 3 * ctypes.sizeof(ctypes.c_void_p),
                                       ctypes.POINTER(ctypes.c_void_p)).contents.value

            # 定义 GetImage 函数原型
            # HRESULT GetImage(SIZE size, SIIGBF flags, HBITMAP* phbm);
            GetImage = ctypes.WINFUNCTYPE(
                ctypes.c_long,  # HRESULT
                ctypes.c_void_p,  # this
                ctypes.c_long,  # cx
                ctypes.c_long,  # cy
                ctypes.c_uint,  # flags
                ctypes.POINTER(ctypes.c_void_p)  # phbm
            )(get_image_ptr)

            # 调用 GetImage
            hbitmap = ctypes.c_void_p()
            hr = GetImage(
                shell_item_ptr,
                size,  # cx
                size,  # cy
                SIIGBF_ICONONLY | SIIGBF_BIGGERSIZEOK | SIIGBF_SCALEUP,  # 获取图标，允许更大尺寸，允许放大
                byref(hbitmap)
            )

            if hr != 0 or not hbitmap:
                debug(f"IShellItemImageFactory.GetImage失败: {file_path}, hr={hr}")
                return None

            # 将 HBITMAP 转换为 HICON
            # 使用 CreateIconIndirect
            class ICONINFO(ctypes.Structure):
                _fields_ = [
                    ("fIcon", BOOL),
                    ("xHotspot", ctypes.c_uint),
                    ("yHotspot", ctypes.c_uint),
                    ("hbmMask", ctypes.c_void_p),
                    ("hbmColor", ctypes.c_void_p)
                ]

            # 创建掩码位图（全透明）
            CreateBitmap = windll.gdi32.CreateBitmap
            CreateBitmap.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p]
            CreateBitmap.restype = ctypes.c_void_p

            # 获取原始位图信息
            class BITMAP(ctypes.Structure):
                _fields_ = [
                    ("bmType", ctypes.c_long),
                    ("bmWidth", ctypes.c_long),
                    ("bmHeight", ctypes.c_long),
                    ("bmWidthBytes", ctypes.c_long),
                    ("bmPlanes", ctypes.c_ushort),
                    ("bmBitsPixel", ctypes.c_ushort),
                    ("bmBits", ctypes.c_void_p)
                ]

            GetObject = windll.gdi32.GetObjectW
            GetObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
            GetObject.restype = ctypes.c_int

            bmp = BITMAP()
            if GetObject(hbitmap, ctypes.sizeof(bmp), byref(bmp)) == 0:
                debug(f"获取位图信息失败: {file_path}")
                windll.gdi32.DeleteObject(hbitmap)
                return None

            # 创建掩码位图
            hbm_mask = CreateBitmap(bmp.bmWidth, bmp.bmHeight, 1, 1, None)

            icon_info = ICONINFO()
            icon_info.fIcon = True
            icon_info.xHotspot = 0
            icon_info.yHotspot = 0
            icon_info.hbmMask = hbm_mask
            icon_info.hbmColor = hbitmap

            CreateIconIndirect = user32.CreateIconIndirect
            CreateIconIndirect.argtypes = [ctypes.POINTER(ICONINFO)]
            CreateIconIndirect.restype = HICON

            hicon = CreateIconIndirect(byref(icon_info))

            # 清理位图资源
            windll.gdi32.DeleteObject(hbitmap)
            windll.gdi32.DeleteObject(hbm_mask)

            if hicon:
                debug(f"IShellItemImageFactory获取图标成功: {file_path}")
                return hicon
            debug(f"CreateIconIndirect创建图标失败: {file_path}")

        finally:
            # 释放 ShellItem
            if shell_item_ptr:
                # 调用 Release 方法 (vtable 索引2)
                vtable_ptr = ctypes.cast(shell_item_ptr, ctypes.POINTER(ctypes.c_void_p)).contents.value
                if vtable_ptr:
                    release_ptr = ctypes.cast(vtable_ptr + 2 * ctypes.sizeof(ctypes.c_void_p),
                                             ctypes.POINTER(ctypes.c_void_p)).contents.value
                    Release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(release_ptr)
                    Release(shell_item_ptr)

    except (OSError, IOError, PermissionError, FileNotFoundError) as e:
        debug(f"IShellItemImageFactory获取图标失败(文件错误): {file_path}, 错误: {e}")
    except (ValueError, TypeError) as e:
        debug(f"IShellItemImageFactory获取图标失败(数据错误): {file_path}, 错误: {e}")
    except RuntimeError as e:
        debug(f"IShellItemImageFactory获取图标失败(运行时错误): {file_path}, 错误: {e}")

    return None

def hicon_to_pixmap(hicon, size, qt_app, device_pixel_ratio=None, keep_original_size=False):
    """
    将HICON转换为QPixmap

    参数:
        hicon: HICON - 图标句柄
        size: int - 目标大小（逻辑像素）
        qt_app: QApplication - Qt应用实例
        device_pixel_ratio: float - 设备像素比，如果不指定则使用系统主屏幕的DPI
        keep_original_size: bool - 是否保持原始分辨率（点对点渲染），默认为False

    返回:
        QPixmap - 如果转换成功则返回Pixmap，否则返回None
    """
    debug(f"HICON转QPixmap: size={size}, keep_original={keep_original_size}")
    try:
        from PySide6.QtGui import QPixmap, QImage, QPainter, QColor, QTransform, QGuiApplication
        from PySide6.QtCore import Qt, QPoint
        from PIL import Image, ImageFilter, ImageEnhance
        import io

        # 获取设备像素比
        if device_pixel_ratio is None:
            device_pixel_ratio = QGuiApplication.primaryScreen().devicePixelRatio()

        # 使用Windows API获取图标信息
        class ICONINFO(ctypes.Structure):
            _fields_ = [
                ("fIcon", BOOL),
                ("xHotspot", ctypes.c_uint),
                ("yHotspot", ctypes.c_uint),
                ("hbmMask", ctypes.c_void_p),
                ("hbmColor", ctypes.c_void_p)
            ]

        class BITMAP(ctypes.Structure):
            _fields_ = [
                ("bmType", DWORD),
                ("bmWidth", DWORD),
                ("bmHeight", DWORD),
                ("bmWidthBytes", DWORD),
                ("bmPlanes", ctypes.c_ushort),
                ("bmBitsPixel", ctypes.c_ushort),
                ("bmBits", ctypes.c_void_p)
            ]

        GetIconInfo = user32.GetIconInfo
        GetIconInfo.argtypes = [HICON, ctypes.POINTER(ICONINFO)]
        GetIconInfo.restype = BOOL

        GetObjectW = windll.gdi32.GetObjectW
        GetObjectW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        GetObjectW.restype = ctypes.c_int

        GetDIBits = windll.gdi32.GetDIBits
        GetDIBits.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, DWORD, DWORD,
            ctypes.c_void_p, ctypes.c_void_p, UINT
        ]
        GetDIBits.restype = DWORD

        CreateCompatibleDC = windll.gdi32.CreateCompatibleDC
        CreateCompatibleDC.argtypes = [ctypes.c_void_p]
        CreateCompatibleDC.restype = ctypes.c_void_p

        DeleteDC = windll.gdi32.DeleteDC
        DeleteDC.argtypes = [ctypes.c_void_p]
        DeleteDC.restype = BOOL

        SelectObject = windll.gdi32.SelectObject
        SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        SelectObject.restype = ctypes.c_void_p

        DeleteObject = windll.gdi32.DeleteObject
        DeleteObject.argtypes = [ctypes.c_void_p]
        DeleteObject.restype = BOOL

        # 获取图标信息
        icon_info = ICONINFO()
        if not GetIconInfo(hicon, byref(icon_info)):
            debug("GetIconInfo获取图标信息失败")
            return None

        try:
            # 获取彩色位图信息
            bmp = BITMAP()
            if GetObjectW(icon_info.hbmColor, sizeof(bmp), byref(bmp)) == 0:
                debug("GetObjectW获取位图信息失败")
                return None

            width, height = bmp.bmWidth, bmp.bmHeight
            debug(f"图标原始尺寸: {width}x{height}")

            # 为DIB创建BITMAPINFOHEADER
            class BITMAPINFOHEADER(ctypes.Structure):
                _fields_ = [
                    ("biSize", DWORD),
                    ("biWidth", ctypes.c_long),
                    ("biHeight", ctypes.c_long),
                    ("biPlanes", ctypes.c_ushort),
                    ("biBitCount", ctypes.c_ushort),
                    ("biCompression", DWORD),
                    ("biSizeImage", DWORD),
                    ("biXPelsPerMeter", ctypes.c_long),
                    ("biYPelsPerMeter", ctypes.c_long),
                    ("biClrUsed", DWORD),
                    ("biClrImportant", DWORD)
                ]

            bmi_header = BITMAPINFOHEADER()
            bmi_header.biSize = sizeof(bmi_header)
            bmi_header.biWidth = width
            bmi_header.biHeight = -height  # 负高度表示自上而下
            bmi_header.biPlanes = 1
            bmi_header.biBitCount = 32  # 32位ARGB
            bmi_header.biCompression = 0  # BI_RGB

            # 分配内存存储像素数据
            buffer_size = width * height * 4
            buffer = (ctypes.c_ubyte * buffer_size)()

            # 获取设备上下文
            dc = CreateCompatibleDC(None)
            if not dc:
                debug("CreateCompatibleDC创建设备上下文失败")
                return None

            try:
                # 获取像素数据
                bits_copied = GetDIBits(
                    dc, icon_info.hbmColor, 0, height,
                    byref(buffer), byref(bmi_header), 0
                )

                if bits_copied == 0:
                    debug("GetDIBits获取像素数据失败")
                    return None

                # 创建QImage - 使用原始位图数据，保持原始分辨率
                qimage = QImage(buffer, width, height, width * 4, QImage.Format_ARGB32)

                # 如果要求保持原始大小（点对点渲染），直接返回原始尺寸的pixmap
                if keep_original_size:
                    # 深拷贝QImage数据，因为buffer是临时的
                    qimage_copy = qimage.copy()
                    pixmap = QPixmap.fromImage(qimage_copy)
                    # 设置设备像素比为1.0，保持1:1像素映射
                    pixmap.setDevicePixelRatio(1.0)
                    return pixmap

                # 如果图像已经是目标大小，直接返回
                if width == size and height == size:
                    pixmap = QPixmap.fromImage(qimage.copy())
                    pixmap.setDevicePixelRatio(device_pixel_ratio)
                    return pixmap

                # 使用PIL进行高质量缩放和处理
                # 将QImage转换为PIL Image
                from PySide6.QtCore import QBuffer
                qt_buffer = QBuffer()
                qt_buffer.open(QBuffer.OpenModeFlag.WriteOnly)
                qimage.save(qt_buffer, "PNG")
                qt_buffer.seek(0)
                pil_image = Image.open(io.BytesIO(qt_buffer.data())).convert("RGBA")

                # 计算缩放比例
                scale_factor = min(size / width, size / height)
                new_width = int(width * scale_factor)
                new_height = int(height * scale_factor)

                # 使用LANCZOS算法进行高质量缩放
                pil_image = pil_image.resize((new_width, new_height), Image.Resampling.LANCZOS)

                # 应用锐化效果，根据缩放比例调整锐化程度
                if scale_factor < 1.0:  # 缩小图像时需要锐化
                    # 根据缩放比例调整锐化程度，缩放比例越小，锐化越强
                    sharpen_amount = 1.0 + (1.0 - scale_factor) * 0.5
                    sharpener = ImageEnhance.Sharpness(pil_image)
                    pil_image = sharpener.enhance(sharpen_amount)

                    # 应用轻微的边缘增强
                    pil_image = pil_image.filter(ImageFilter.UnsharpMask(radius=1, percent=100, threshold=2))

                # 创建透明背景的新图像
                new_pil_image = Image.new("RGBA", (size, size), (0, 0, 0, 0))

                # 计算居中位置
                x_offset = (size - new_width) // 2
                y_offset = (size - new_height) // 2

                # 将缩放后的图像粘贴到新图像中央
                new_pil_image.paste(pil_image, (x_offset, y_offset), pil_image)

                # 将PIL Image转换回QImage
                temp_buffer = io.BytesIO()
                new_pil_image.save(temp_buffer, format="PNG")
                processed_qimage = QImage.fromData(temp_buffer.getvalue(), "PNG")

                # 转换为QPixmap
                pixmap = QPixmap.fromImage(processed_qimage)
                pixmap.setDevicePixelRatio(device_pixel_ratio)

                return pixmap
            finally:
                DeleteDC(dc)
        finally:
            # 清理资源
            if icon_info.hbmMask:
                DeleteObject(icon_info.hbmMask)
            if icon_info.hbmColor:
                DeleteObject(icon_info.hbmColor)

        debug("HICON转QPixmap主流程失败")
        return None
    except (ImportError, OSError, IOError) as e:
        # 如果PIL处理失败，回退到Qt的处理方式
        debug(f"PIL图标处理失败，回退到Qt方式: {e}")
        try:
            from PySide6.QtGui import QPixmap, QImage, QPainter
            from PySide6.QtCore import Qt
            
            # 获取图标信息
            icon_info = ICONINFO()
            if not GetIconInfo(hicon, byref(icon_info)):
                return None
            
            try:
                # 获取彩色位图信息
                bmp = BITMAP()
                if GetObjectW(icon_info.hbmColor, sizeof(bmp), byref(bmp)) == 0:
                    return None
                
                width, height = bmp.bmWidth, bmp.bmHeight
                
                # 为DIB创建BITMAPINFOHEADER
                class BITMAPINFOHEADER(ctypes.Structure):
                    _fields_ = [
                        ("biSize", DWORD),
                        ("biWidth", ctypes.c_long),
                        ("biHeight", ctypes.c_long),
                        ("biPlanes", ctypes.c_ushort),
                        ("biBitCount", ctypes.c_ushort),
                        ("biCompression", DWORD),
                        ("biSizeImage", DWORD),
                        ("biXPelsPerMeter", ctypes.c_long),
                        ("biYPelsPerMeter", ctypes.c_long),
                        ("biClrUsed", DWORD),
                        ("biClrImportant", DWORD)
                    ]
                
                bmi_header = BITMAPINFOHEADER()
                bmi_header.biSize = sizeof(bmi_header)
                bmi_header.biWidth = width
                bmi_header.biHeight = -height
                bmi_header.biPlanes = 1
                bmi_header.biBitCount = 32
                bmi_header.biCompression = 0
                
                # 分配内存存储像素数据
                buffer_size = width * height * 4
                buffer = (ctypes.c_ubyte * buffer_size)()
                
                # 获取设备上下文
                dc = CreateCompatibleDC(None)
                if not dc:
                    return None
                
                try:
                    # 获取像素数据
                    bits_copied = GetDIBits(
                        dc, icon_info.hbmColor, 0, height, 
                        byref(buffer), byref(bmi_header), 0
                    )
                    
                    if bits_copied == 0:
                        return None
                    
                    # 创建QImage
                    qimage = QImage(buffer, width, height, width * 4, QImage.Format_ARGB32)
                    
                    # 使用Qt的高质量缩放，将图像缩放到实际需要的像素大小
                    # size是逻辑像素大小，实际像素大小 = size * device_pixel_ratio
                    actual_size = int(size * device_pixel_ratio)
                    scaled_qimage = qimage.scaled(
                        actual_size, actual_size, 
                        Qt.KeepAspectRatio, 
                        Qt.SmoothTransformation
                    )
                    
                    # 创建最终Pixmap，设置正确的设备像素比
                    pixmap = QPixmap.fromImage(scaled_qimage)
                    pixmap.setDevicePixelRatio(device_pixel_ratio)
                    
                    debug("Qt回退方式处理图标成功")
                    return pixmap
                finally:
                    DeleteDC(dc)
            finally:
                if icon_info.hbmMask:
                    DeleteObject(icon_info.hbmMask)
                if icon_info.hbmColor:
                    DeleteObject(icon_info.hbmColor)
        except (OSError, ctypes.WinError) as fallback_e:
            debug(f"Qt回退图标处理也失败: {fallback_e}")
            return None

# 模块导出
__all__ = [
    "get_highest_resolution_icon",
    "get_all_icons_from_exe",
    "hicon_to_pixmap",
    "get_lnk_target",
    "DestroyIcon"
]