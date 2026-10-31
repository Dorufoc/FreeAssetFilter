cmake_minimum_required(VERSION 3.20)
project(SopeekInstaller LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# 自动收集源文件（§13）：新增 .cpp 无需再改本文件。resources/app.rc 仍显式列出。
# 说明：此处以 CONFIGURE_DEPENDS 作为 GLOB 结果集合的变量名（与计划冻结写法
# `file(GLOB CONFIGURE_DEPENDS "src/*.cpp" "src/render/*.cpp")` 一致），由
# add_executable 通过 ${CONFIGURE_DEPENDS} 引用；build.ps1 每次全新配置，
# 新增文件在配置期即被纳入。
file(GLOB CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/src/*.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/render/*.cpp"
)

add_executable(SopeekInstaller WIN32
    ${CONFIGURE_DEPENDS}
    resources/app.rc
)

# Todo 19（§17）：测试构建开关。默认 OFF ⇒ 生产构建分毫不变；仅测试 GUI 构建
# （tools/build_test_gui.ps1）传 -DSPK_TESTMODE=ON。除本 include 外无其他改动。
include(cmake/test_mode.cmake)

target_compile_definitions(SopeekInstaller PRIVATE
    UNICODE _UNICODE NOMINMAX
    # MinGW 默认 _WIN32_WINNT=0x601 会隐藏 DCompositionCreateDevice2 等原型。
    _WIN32_WINNT=0x0A00
    WINVER=0x0A00)
target_link_libraries(SopeekInstaller PRIVATE
    d2d1 dwrite dcomp dxgi d3d11 dwmapi windowscodecs uxtheme uuid shcore
    comctl32 shell32 shlwapi ole32)
# Keep the bootstrapper self-contained: users do not need the MSYS2 runtime.
target_link_options(SopeekInstaller PRIVATE -static-libgcc -static-libstdc++ -static)
target_include_directories(SopeekInstaller PRIVATE src)
set_target_properties(SopeekInstaller PROPERTIES OUTPUT_NAME "SopeekInstaller")
