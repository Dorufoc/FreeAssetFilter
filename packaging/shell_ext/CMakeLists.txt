cmake_minimum_required(VERSION 3.20)
project(SopeekShellExt LANGUAGES CXX)

# MinGW 构建的 in-proc COM 组件。由 packaging/installer/build.ps1 在打包安装包
# 之前调用（也可单独调用 build.ps1），产物随 payload 安装到 $INSTDIR。
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_library(SopeekShellExt SHARED
    src/shell_ext.cpp
    src/shell_ext.def
)

target_compile_definitions(SopeekShellExt PRIVATE
    UNICODE _UNICODE NOMINMAX WIN32_LEAN_AND_MEAN
    _WIN32_WINNT=0x0A00
    WINVER=0x0A00)

# 源码是 UTF-8，且标题常量是中文宽字符串字面量：显式声明输入字符集，
# 避免构建机区域设置变化时 L"使用Sopeek打开" 被按 ANSI 解读。
target_compile_options(SopeekShellExt PRIVATE
    -finput-charset=UTF-8
    -Wall -Wextra -Wpedantic)

target_link_libraries(SopeekShellExt PRIVATE shell32 shlwapi ole32)

# 与安装器一致：不引入 MSYS2 运行时 DLL（目标机只应看到 SopeekShellExt.dll）。
target_link_options(SopeekShellExt PRIVATE -static-libgcc -static-libstdc++ -static)

set_target_properties(SopeekShellExt PROPERTIES
    PREFIX ""
    OUTPUT_NAME "SopeekShellExt")
