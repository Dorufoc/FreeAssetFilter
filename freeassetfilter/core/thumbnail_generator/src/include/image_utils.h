#pragma once

#include <string>

// Include OpenCV headers or dummy implementation
#ifdef ENABLE_OPENCV_SUPPORT
#include <opencv2/opencv.hpp>
#else
#include <opencv_dummy.hpp>
#endif

class ImageUtils {
public:
    static bool IsRawImage(const std::string& filename);
    static bool IsSupportedFormat(const std::string& filename);
    
    static cv::Mat ReadImage(const std::string& filename);
    static cv::Mat ReadRawImage(const std::string& filename);
    static cv::Mat ReadRegularImage(const std::string& filename);
    
    static cv::Mat ResizeImage(const cv::Mat& image, int max_width, int max_height);
    static bool WriteImage(const cv::Mat& image, const std::string& output_path, int quality);
    
    static std::string GetFileExtension(const std::string& filename);
    static std::string GetFileNameWithoutExtension(const std::string& filename);
    static std::string GenerateThumbnailFilename(const std::string& original_filename, const std::string& format);
};
