#include "include/processor.h"
#include "include/image_utils.h"
#include "include/logger.h"
#include <filesystem>
#include <thread>
#include <mutex>
#include <queue>
#include <algorithm>

namespace fs = std::filesystem;

ThumbnailProcessor::ThumbnailProcessor(const ProcessingConfig& config)
    : config_(config) {
    LOG_INFO("Initialized ThumbnailProcessor with config:");
    LOG_INFO("  Input dir: " + config.input_dir);
    LOG_INFO("  Output dir: " + config.output_dir);
    LOG_INFO("  Max width: " + std::to_string(config.max_width));
    LOG_INFO("  Max height: " + std::to_string(config.max_height));
    LOG_INFO("  Threads: " + std::to_string(config.threads));
    LOG_INFO("  Quality: " + std::to_string(config.quality));
    LOG_INFO("  Output format: " + config.output_format);
}

ThumbnailProcessor::~ThumbnailProcessor() {}

std::vector<std::string> ThumbnailProcessor::GetImageFiles(const std::string& dir) {
    std::vector<std::string> image_files;
    
    try {
        if (!fs::exists(dir)) {
            LOG_ERROR("Directory does not exist: " + dir);
            return image_files;
        }
        
        for (const auto& entry : fs::directory_iterator(dir)) {
            if (entry.is_regular_file()) {
                std::string filename = entry.path().filename().string();
                if (IsSupportedImage(filename)) {
                    image_files.push_back(entry.path().string());
                }
            }
        }
        
        LOG_INFO("Found " + std::to_string(image_files.size()) + " supported image files in " + dir);
    } catch (const fs::filesystem_error& e) {
        LOG_ERROR("Error accessing directory " + dir + ": " + e.what());
    }
    
    return image_files;
}

bool ThumbnailProcessor::IsSupportedImage(const std::string& filename) {
    return ImageUtils::IsSupportedFormat(filename);
}

ThumbnailResult ThumbnailProcessor::ProcessSingleImage(const std::string& input_path) {
    ThumbnailResult result;
    result.original_filename = fs::path(input_path).filename().string();
    
    try {
        // 读取图片
        cv::Mat image = ImageUtils::ReadImage(input_path);
        if (image.empty()) {
            result.success = false;
            result.error_message = "Failed to read image";
            LOG_ERROR("Failed to read image: " + input_path);
            return result;
        }
        
        // 调整尺寸
        cv::Mat resized_image = ImageUtils::ResizeImage(image, config_.max_width, config_.max_height);
        if (resized_image.empty()) {
            result.success = false;
            result.error_message = "Failed to resize image";
            LOG_ERROR("Failed to resize image: " + input_path);
            return result;
        }
        
        // 生成缩略图文件名和路径
        std::string thumbnail_filename = ImageUtils::GenerateThumbnailFilename(result.original_filename, config_.output_format);
        std::filesystem::path output_dir_path(config_.output_dir);
        std::string thumbnail_path = (output_dir_path / thumbnail_filename).string();
        
        // 确保输出目录存在
        fs::create_directories(config_.output_dir);
        
        // 写入缩略图
        if (!ImageUtils::WriteImage(resized_image, thumbnail_path, config_.quality)) {
            result.success = false;
            result.error_message = "Failed to write thumbnail";
            LOG_ERROR("Failed to write thumbnail: " + thumbnail_path);
            return result;
        }
        
        // 设置成功结果
        result.success = true;
        result.thumbnail_filename = thumbnail_filename;
        result.thumbnail_path = thumbnail_path;
        LOG_INFO("Successfully processed: " + input_path + " -> " + thumbnail_path);
        
    } catch (const std::exception& e) {
        result.success = false;
        result.error_message = e.what();
        LOG_ERROR("Exception processing image " + input_path + ": " + e.what());
    }
    
    return result;
}

std::vector<ThumbnailResult> ThumbnailProcessor::ProcessAll() {
    std::vector<std::string> image_files = GetImageFiles(config_.input_dir);
    std::vector<ThumbnailResult> results;
    
    if (image_files.empty()) {
        LOG_WARNING("No supported image files found in " + config_.input_dir);
        return results;
    }
    
    // 创建结果存储和同步机制
    std::vector<ThumbnailResult> all_results;
    std::mutex results_mutex;
    std::queue<std::string> image_queue;
    std::mutex queue_mutex;
    
    // 填充任务队列
    for (const auto& file : image_files) {
        image_queue.push(file);
    }
    
    // 线程函数
    auto worker = [&]() {
        while (true) {
            std::string image_path;
            
            {   // 加锁获取任务
                std::unique_lock<std::mutex> lock(queue_mutex);
                if (image_queue.empty()) {
                    break;
                }
                
                image_path = image_queue.front();
                image_queue.pop();
            }
            
            // 处理图片
            ThumbnailResult result = ProcessSingleImage(image_path);
            
            // 保存结果
            {   // 加锁保存结果
                std::unique_lock<std::mutex> lock(results_mutex);
                all_results.push_back(result);
            }
        }
    };
    
    // 创建和启动线程
    int thread_count = std::min(config_.threads, static_cast<int>(image_files.size()));
    std::vector<std::thread> threads;
    
    LOG_INFO("Starting " + std::to_string(thread_count) + " worker threads");
    
    for (int i = 0; i < thread_count; ++i) {
        threads.emplace_back(worker);
    }
    
    // 等待所有线程完成
    for (auto& thread : threads) {
        thread.join();
    }
    
    LOG_INFO("Finished processing all images");
    
    return all_results;
}
