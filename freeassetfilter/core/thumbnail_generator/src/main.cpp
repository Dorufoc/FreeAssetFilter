#include "include/processor.h"
#include "include/result.h"
#include "include/logger.h"
#include <iostream>
#include <cstdlib>
#include <getopt.h>
#include <string>
#include <filesystem>

// 默认配置
const int DEFAULT_MAX_WIDTH = 256;
const int DEFAULT_MAX_HEIGHT = 256;
const int DEFAULT_THREADS = 4;
const int DEFAULT_QUALITY = 85;
const std::string DEFAULT_OUTPUT_FORMAT = "jpg";
const std::string DEFAULT_RETURN_FORMAT = "json";

// 帮助信息
void PrintHelp(const char* program_name) {
    std::cout << "Usage: " << program_name << " [options]\n";
    std::cout << "Options:\n";
    std::cout << "  -h, --help                Show this help message\n";
    std::cout << "  -i, --input <dir>         Input directory path\n";
    std::cout << "  -o, --output <dir>        Output directory path (default: cache directory)\n";
    std::cout << "  -w, --max-width <int>     Maximum width in pixels (default: " << DEFAULT_MAX_WIDTH << ")\n";
    std::cout << "  -H, --max-height <int>    Maximum height in pixels (default: " << DEFAULT_MAX_HEIGHT << ")\n";
    std::cout << "  -t, --threads <int>       Number of threads to use (default: " << DEFAULT_THREADS << ")\n";
    std::cout << "  -q, --quality <int>       Output image quality (0-100, default: " << DEFAULT_QUALITY << ")\n";
    std::cout << "  -f, --format <format>     Output image format (default: " << DEFAULT_OUTPUT_FORMAT << ")\n";
    std::cout << "  -r, --return-format <fmt> Return format (json, text, csv, default: " << DEFAULT_RETURN_FORMAT << ")\n";
    std::cout << "  -v, --verbose             Enable verbose logging\n";
    std::cout << "\nSupported image formats: jpg, jpeg, png, gif, bmp, tiff, webp\n";
    std::cout << "Supported RAW formats: arw, dng, cr2, nef, orf, rw2, pef\n";
}

// 获取默认缓存目录
std::string GetDefaultCacheDir() {
    std::string cache_dir;
    
    #ifdef _WIN32
        // Windows: %LOCALAPPDATA%/FreeAssetFilter/cache
        const char* local_app_data = std::getenv("LOCALAPPDATA");
        if (local_app_data) {
            cache_dir = std::string(local_app_data) + "/FreeAssetFilter/cache";
        } else {
            cache_dir = "./cache";
        }
    #elif __APPLE__
        // macOS: ~/Library/Caches/FreeAssetFilter
        const char* home = std::getenv("HOME");
        if (home) {
            cache_dir = std::string(home) + "/Library/Caches/FreeAssetFilter";
        } else {
            cache_dir = "./cache";
        }
    #else
        // Linux: ~/.cache/FreeAssetFilter
        const char* home = std::getenv("HOME");
        if (home) {
            cache_dir = std::string(home) + "/.cache/FreeAssetFilter";
        } else {
            cache_dir = "./cache";
        }
    #endif
    
    return cache_dir;
}

int main(int argc, char* argv[]) {
    // 命令行参数定义
    static struct option long_options[] = {
        {"help", no_argument, 0, 'h'},
        {"input", required_argument, 0, 'i'},
        {"output", required_argument, 0, 'o'},
        {"max-width", required_argument, 0, 'w'},
        {"max-height", required_argument, 0, 'H'},
        {"threads", required_argument, 0, 't'},
        {"quality", required_argument, 0, 'q'},
        {"format", required_argument, 0, 'f'},
        {"return-format", required_argument, 0, 'r'},
        {"verbose", no_argument, 0, 'v'},
        {0, 0, 0, 0}
    };
    
    // 初始化配置
    ProcessingConfig config;
    std::string return_format = DEFAULT_RETURN_FORMAT;
    bool verbose = false;
    
    // 解析命令行参数
    int opt;
    int option_index = 0;
    
    while ((opt = getopt_long(argc, argv, "hi:o:w:H:t:q:f:r:v", long_options, &option_index)) != -1) {
        switch (opt) {
            case 'h':
                PrintHelp(argv[0]);
                return 0;
            case 'i':
                config.input_dir = optarg;
                break;
            case 'o':
                config.output_dir = optarg;
                break;
            case 'w':
                config.max_width = std::atoi(optarg);
                break;
            case 'H':
                config.max_height = std::atoi(optarg);
                break;
            case 't':
                config.threads = std::atoi(optarg);
                break;
            case 'q':
                config.quality = std::atoi(optarg);
                break;
            case 'f':
                config.output_format = optarg;
                break;
            case 'r':
                return_format = optarg;
                break;
            case 'v':
                verbose = true;
                break;
            default:
                PrintHelp(argv[0]);
                return 1;
        }
    }
    
    // 验证必填参数
    if (config.input_dir.empty()) {
        std::cerr << "Error: Input directory is required\n";
        PrintHelp(argv[0]);
        return 1;
    }
    
    // 设置默认值
    if (config.output_dir.empty()) {
        config.output_dir = GetDefaultCacheDir();
    }
    
    if (config.max_width <= 0) {
        config.max_width = DEFAULT_MAX_WIDTH;
    }
    
    if (config.max_height <= 0) {
        config.max_height = DEFAULT_MAX_HEIGHT;
    }
    
    if (config.threads <= 0) {
        config.threads = DEFAULT_THREADS;
    }
    
    if (config.quality <= 0 || config.quality > 100) {
        config.quality = DEFAULT_QUALITY;
    }
    
    if (config.output_format.empty()) {
        config.output_format = DEFAULT_OUTPUT_FORMAT;
    }
    
    // 初始化日志
    if (verbose) {
        Logger::GetInstance().SetLogLevel(LogLevel::DEBUG);
    } else {
        Logger::GetInstance().SetLogLevel(LogLevel::INFO);
    }
    
    LOG_INFO("Starting thumbnail generation");
    
    try {
        // 创建处理器
        ThumbnailProcessor processor(config);
        
        // 处理所有图片
        auto results = processor.ProcessAll();
        
        // 输出结果
        std::string output;
        if (return_format == "json") {
            output = ResultFormatter::FormatAsJson(results);
        } else if (return_format == "text") {
            output = ResultFormatter::FormatAsText(results);
        } else if (return_format == "csv") {
            output = ResultFormatter::FormatAsCsv(results);
        } else {
            std::cerr << "Error: Unsupported return format: " << return_format << "\n";
            return 1;
        }
        
        std::cout << output << std::endl;
        
        LOG_INFO("Thumbnail generation completed");
        
        // 检查是否有错误
        bool has_errors = false;
        for (const auto& result : results) {
            if (!result.success) {
                has_errors = true;
                break;
            }
        }
        
        return has_errors ? 1 : 0;
        
    } catch (const std::exception& e) {
        LOG_CRITICAL("Critical error during thumbnail generation: " + std::string(e.what()));
        std::cerr << "Critical error: " << e.what() << std::endl;
        return 1;
    }
}
