cmake_minimum_required(VERSION 3.12)

# 项目名称
project(thumbnail_generator VERSION 1.0 LANGUAGES CXX)

# 设置C++标准
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# 设置编译选项
if(MSVC)
    # Windows-specific options for Visual Studio
    add_compile_options(/W4 /WX /utf-8)
    add_definitions(-DNOMINMAX)
else()
    # Linux/macOS/MinGW-w64 options
    add_compile_options(-Wall -Wextra -Wpedantic)
    if(NOT MINGW)
        add_compile_options(-Werror)
    endif()
endif()

# 设置输出目录
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_SOURCE_DIR}/build)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY_DEBUG ${CMAKE_SOURCE_DIR}/build)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY_RELEASE ${CMAKE_SOURCE_DIR}/build)

# ============== 依赖管理 ==============

# 1. OpenCV依赖 - 可选
find_package(OpenCV QUIET)
if(OpenCV_FOUND)
    message(STATUS "✓ OpenCV found, enabling full image support")
    add_definitions(-DENABLE_OPENCV_SUPPORT)
    include_directories(${OpenCV_INCLUDE_DIRS})
else()
    message(STATUS "⚠ OpenCV not found, building with limited functionality")
    
    # 生成简化的OpenCV替代头文件
    configure_file(
        ${CMAKE_SOURCE_DIR}/cmake/opencv_dummy.hpp.in
        ${CMAKE_BINARY_DIR}/opencv_dummy.hpp
        @ONLY
    )
    include_directories(${CMAKE_BINARY_DIR})
endif()

# 2. LibRaw依赖 - 可选
find_package(LibRaw QUIET)
if(LIBRAW_FOUND)
    message(STATUS "✓ LibRaw found, enabling RAW image support")
    add_definitions(-DENABLE_RAW_SUPPORT)
    include_directories(${LIBRAW_INCLUDE_DIRS})
else()
    message(STATUS "⚠ LibRaw not found, RAW image support will be limited")
endif()

# ============== 源文件配置 ==============

# 头文件目录
include_directories(${CMAKE_SOURCE_DIR}/src/include)

# 源文件列表
set(SOURCES
    src/main.cpp
    src/processor.cpp
    src/image_utils.cpp
    src/logger.cpp
    src/result.cpp
)

# ============== 可执行文件配置 ==============

# 创建可执行文件
add_executable(thumbnail_generator ${SOURCES})

# 链接第三方库
if(OpenCV_FOUND)
    target_link_libraries(thumbnail_generator ${OpenCV_LIBS})
endif()

if(LIBRAW_FOUND)
    target_link_libraries(thumbnail_generator ${LIBRAW_LIBRARIES})
endif()

# ============== 安装配置 ==============

install(TARGETS thumbnail_generator DESTINATION bin)

# ============== 打包配置 ==============

set(CPACK_PROJECT_NAME ${PROJECT_NAME})
set(CPACK_PROJECT_VERSION ${PROJECT_VERSION})
include(CPack)

# ============== 打印构建信息 ==============

message(STATUS "")
message(STATUS "=== 构建配置信息 ===")
message(STATUS "构建类型: ${CMAKE_BUILD_TYPE}")
message(STATUS "编译器: ${CMAKE_CXX_COMPILER_ID} ${CMAKE_CXX_COMPILER_VERSION}")
message(STATUS "输出目录: ${CMAKE_RUNTIME_OUTPUT_DIRECTORY}")
message(STATUS "OpenCV支持: ${OpenCV_FOUND}")
message(STATUS "LibRaw支持: ${LIBRAW_FOUND}")
message(STATUS "")