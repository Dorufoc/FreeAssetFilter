cmake_minimum_required(VERSION 3.20)
project(FreeAssetFilterInstaller LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_executable(FreeAssetFilterInstaller WIN32
    src/main.cpp
    src/installer_window.cpp
    src/installer_window.h
    src/duilib/duilib.h
    src/duilib/duilib.cpp
    resources/app.rc
)

target_compile_definitions(FreeAssetFilterInstaller PRIVATE UNICODE _UNICODE NOMINMAX)
target_link_libraries(FreeAssetFilterInstaller PRIVATE comctl32 shell32 shlwapi ole32)
# Keep the bootstrapper self-contained: users do not need the MSYS2 runtime.
target_link_options(FreeAssetFilterInstaller PRIVATE -static-libgcc -static-libstdc++ -static)
target_include_directories(FreeAssetFilterInstaller PRIVATE src)
set_target_properties(FreeAssetFilterInstaller PROPERTIES OUTPUT_NAME "FreeAssetFilterInstaller")
