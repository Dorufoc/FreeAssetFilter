#include "include/image_utils.h"
#include "include/logger.h"
#include <algorithm>
#include <filesystem>
#include <vector>

// 支持的常规图片格式
const std::vector<std::string> REGULAR_FORMATS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp"};

// 支持的RAW格式
const std::vector<std::string> RAW_FORMATS = {".arw", ".dng", ".cr2", ".nef", ".orf", ".rw2", ".pef"};

bool ImageUtils::IsRawImage(const std::string& filename) {
    std::string ext = GetFileExtension(filename);
    std::transform(ext.begin(), ext.end(), ext.begin(), ::tolower);
    return std::find(RAW_FORMATS.begin(), RAW_FORMATS.end(), ext) != RAW_FORMATS.end();
}

bool ImageUtils::IsSupportedFormat(const std::string& filename) {
    std::string ext = GetFileExtension(filename);
    std::transform(ext.begin(), ext.end(), ext.begin(), ::tolower);
    
    return (std::find(REGULAR_FORMATS.begin(), REGULAR_FORMATS.end(), ext) != REGULAR_FORMATS.end()) ||
           (std::find(RAW_FORMATS.begin(), RAW_FORMATS.end(), ext) != RAW_FORMATS.end());
}

cv::Mat ImageUtils::ReadImage(const std::string& filename) {
    if (IsRawImage(filename)) {
        return ReadRawImage(filename);
    } else {
        return ReadRegularImage(filename);
    }
}

cv::Mat ImageUtils::ReadRawImage(const std::string& filename) {
    LOG_WARNING("RAW image support is not fully implemented yet: " + filename);
    // 这里应该集成libraw库来处理RAW格式
    // 目前返回一个空图像，后续需要扩展
    return cv::Mat();
}

cv::Mat ImageUtils::ReadRegularImage(const std::string& filename) {
    cv::Mat image = cv::imread(filename, cv::IMREAD_COLOR);
    if (image.empty()) {
        LOG_ERROR("Failed to read image: " + filename);
    }
    return image;
}

cv::Mat ImageUtils::ResizeImage(const cv::Mat& image, int max_width, int max_height) {
    if (image.empty()) {
        return image;
    }
    
    int original_width = image.cols;
    int original_height = image.rows;
    
    double aspect_ratio = static_cast<double>(original_width) / original_height;
    int new_width, new_height;
    
    if (original_width > original_height) {
        // 横向图片
        new_width = std::min(original_width, max_width);
        new_height = static_cast<int>(new_width / aspect_ratio);
        if (new_height > max_height) {
            new_height = max_height;
            new_width = static_cast<int>(new_height * aspect_ratio);
        }
    } else {
        // 纵向图片
        new_height = std::min(original_height, max_height);
        new_width = static_cast<int>(new_height * aspect_ratio);
        if (new_width > max_width) {
            new_width = max_width;
            new_height = static_cast<int>(new_width / aspect_ratio);
        }
    }
    
    cv::Mat resized_image;
    cv::resize(image, resized_image, cv::Size(new_width, new_height), 0, 0, cv::INTER_AREA);
    
    return resized_image;
}

bool ImageUtils::WriteImage(const cv::Mat& image, const std::string& output_path, int quality) {
    if (image.empty()) {
        LOG_ERROR("Cannot write empty image: " + output_path);
        return false;
    }
    
    std::vector<int> params;
    std::string ext = GetFileExtension(output_path);
    std::transform(ext.begin(), ext.end(), ext.begin(), ::tolower);
    
    if (ext == ".jpg" || ext == ".jpeg") {
        params.push_back(cv::IMWRITE_JPEG_QUALITY);
        params.push_back(quality);
    } else if (ext == ".png") {
        params.push_back(cv::IMWRITE_PNG_COMPRESSION);
        params.push_back(9 - (quality / 10)); // PNG压缩等级0-9
    } else if (ext == ".webp") {
        params.push_back(cv::IMWRITE_WEBP_QUALITY);
        params.push_back(quality);
    }
    
    if (!cv::imwrite(output_path, image, params)) {
        LOG_ERROR("Failed to write image: " + output_path);
        return false;
    }
    
    return true;
}

std::string ImageUtils::GetFileExtension(const std::string& filename) {
    size_t dot_pos = filename.find_last_of(".");
    if (dot_pos == std::string::npos) {
        return "";
    }
    return filename.substr(dot_pos);
}

std::string ImageUtils::GetFileNameWithoutExtension(const std::string& filename) {
    size_t dot_pos = filename.find_last_of(".");
    if (dot_pos == std::string::npos) {
        return filename;
    }
    return filename.substr(0, dot_pos);
}

std::string ImageUtils::GenerateThumbnailFilename(const std::string& original_filename, const std::string& format) {
    std::string base_name = GetFileNameWithoutExtension(original_filename);
    return base_name + "_thumb." + format;
}