#ifndef OPENCV_HPP
#define OPENCV_HPP

namespace cv {
    class Mat {
    public:
        Mat() {};
        bool empty() const { return true; }
        int cols = 0;
        int rows = 0;
    };
    
    // 简单的常量定义
    static const int IMREAD_COLOR = 1;
    static const int IMWRITE_JPEG_QUALITY = 1;
    static const int IMWRITE_PNG_COMPRESSION = 16;
    static const int IMWRITE_WEBP_QUALITY = 64;
    static const int INTER_AREA = 3;
    
    // 简单的Size类
    class Size {
    public:
        Size(int w, int h) : width(w), height(h) {};
        int width, height;
    };
    
    // 简单的函数声明
    Mat imread(const std::string& filename, int flags);
    bool imwrite(const std::string& filename, const Mat& img, const std::vector<int>& params);
    void resize(const Mat& src, Mat& dst, Size dsize, double fx = 0, double fy = 0, int interpolation = INTER_AREA);
}

#endif // OPENCV_HPP
