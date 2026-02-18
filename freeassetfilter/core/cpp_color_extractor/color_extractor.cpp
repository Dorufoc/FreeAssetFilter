// color_extractor.cpp
// C++ 实现的高性能封面颜色提取器
// 使用 K-Means 聚类和 CIEDE2000 色差算法

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>

#include <vector>
#include <cmath>
#include <algorithm>
#include <random>
#include <cstring>
#include <stdexcept>
#include <string>

// 定义 M_PI（如果未定义）
#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

// OpenMP 支持
#ifdef _OPENMP
#include <omp.h>
#endif

// 版本号
#define VERSION "1.0.0"

namespace py = pybind11;

// ============================================================================
// 数据结构定义
// ============================================================================

struct RGB {
    uint8_t r, g, b;
    
    RGB() : r(0), g(0), b(0) {}
    RGB(uint8_t r_, uint8_t g_, uint8_t b_) : r(r_), g(g_), b(b_) {}
};

struct Lab {
    float L, a, b;
    
    Lab() : L(0), a(0), b(0) {}
    Lab(float L_, float a_, float b_) : L(L_), a(a_), b(b_) {}
};

struct Cluster {
    Lab centroid;
    size_t size;
    
    Cluster() : centroid(), size(0) {}
    Cluster(const Lab& c, size_t s) : centroid(c), size(s) {}
};

// ============================================================================
// 颜色空间转换
// ============================================================================

// Gamma 校正：sRGB 到线性 RGB
inline float gamma_correct(float c) {
    if (c > 0.04045f) {
        return std::pow((c + 0.055f) / 1.055f, 2.4f);
    }
    return c / 12.92f;
}

// Gamma 校正：线性 RGB 到 sRGB
inline float gamma_uncorrect(float c) {
    if (c > 0.0031308f) {
        return 1.055f * std::pow(c, 1.0f / 2.4f) - 0.055f;
    }
    return 12.92f * c;
}

// RGB 转 Lab
Lab rgb_to_lab(uint8_t r, uint8_t g, uint8_t b) {
    // 归一化到 [0, 1]
    float rf = r / 255.0f;
    float gf = g / 255.0f;
    float bf = b / 255.0f;
    
    // Gamma 校正
    rf = gamma_correct(rf);
    gf = gamma_correct(gf);
    bf = gamma_correct(bf);
    
    // 转换到 XYZ
    float x = rf * 0.4124f + gf * 0.3576f + bf * 0.1805f;
    float y = rf * 0.2126f + gf * 0.7152f + bf * 0.0722f;
    float z = rf * 0.0193f + gf * 0.1192f + bf * 0.9505f;
    
    // XYZ 到 Lab
    x /= 0.95047f;
    y /= 1.00000f;
    z /= 1.08883f;
    
    auto f = [](float t) -> float {
        if (t > 0.008856f) {
            return std::cbrt(t);
        }
        return 7.787f * t + 16.0f / 116.0f;
    };
    
    float fx = f(x);
    float fy = f(y);
    float fz = f(z);
    
    Lab lab;
    lab.L = 116.0f * fy - 16.0f;
    lab.a = 500.0f * (fx - fy);
    lab.b = 200.0f * (fy - fz);
    
    return lab;
}

// Lab 转 RGB
RGB lab_to_rgb(const Lab& lab) {
    float fy = (lab.L + 16.0f) / 116.0f;
    float fx = lab.a / 500.0f + fy;
    float fz = fy - lab.b / 200.0f;
    
    auto f_inv = [](float t) -> float {
        float t3 = t * t * t;
        if (t3 > 0.008856f) {
            return t3;
        }
        return (t - 16.0f / 116.0f) / 7.787f;
    };
    
    float x = f_inv(fx) * 0.95047f;
    float y = f_inv(fy) * 1.00000f;
    float z = f_inv(fz) * 1.08883f;
    
    // XYZ 到线性 RGB
    float rf = x *  3.2406f + y * -1.5372f + z * -0.4986f;
    float gf = x * -0.9689f + y *  1.8758f + z *  0.0415f;
    float bf = x *  0.0557f + y * -0.2040f + z *  1.0570f;
    
    // Gamma 校正
    rf = gamma_uncorrect(rf);
    gf = gamma_uncorrect(gf);
    bf = gamma_uncorrect(bf);
    
    // 限制到 [0, 1] 并转换为 uint8_t
    RGB rgb;
    rgb.r = static_cast<uint8_t>(std::max(0.0f, std::min(1.0f, rf)) * 255.0f + 0.5f);
    rgb.g = static_cast<uint8_t>(std::max(0.0f, std::min(1.0f, gf)) * 255.0f + 0.5f);
    rgb.b = static_cast<uint8_t>(std::max(0.0f, std::min(1.0f, bf)) * 255.0f + 0.5f);
    
    return rgb;
}

// ============================================================================
// CIEDE2000 色差计算
// ============================================================================

float ciede2000(const Lab& lab1, const Lab& lab2) {
    float L1 = lab1.L, a1 = lab1.a, b1 = lab1.b;
    float L2 = lab2.L, a2 = lab2.a, b2 = lab2.b;
    
    // 计算 C 和 h
    float C1 = std::sqrt(a1 * a1 + b1 * b1);
    float C2 = std::sqrt(a2 * a2 + b2 * b2);
    float C_avg = (C1 + C2) / 2.0f;
    
    // 计算 G
    float C_avg7 = std::pow(C_avg, 7);
    float G = 0.5f * (1.0f - std::sqrt(C_avg7 / (C_avg7 + 6103515625.0f))); // 25^7
    
    // 计算 a'
    float a1_prime = a1 * (1.0f + G);
    float a2_prime = a2 * (1.0f + G);
    
    // 计算 C'
    float C1_prime = std::sqrt(a1_prime * a1_prime + b1 * b1);
    float C2_prime = std::sqrt(a2_prime * a2_prime + b2 * b2);
    
    // 计算 h'
    auto atan2_deg = [](float y, float x) -> float {
        float rad = std::atan2(y, x);
        float deg = rad * 180.0f / static_cast<float>(M_PI);
        if (deg < 0) deg += 360.0f;
        return deg;
    };
    
    float h1_prime = atan2_deg(b1, a1_prime);
    float h2_prime = atan2_deg(b2, a2_prime);
    
    // 计算 ΔL', ΔC', ΔH'
    float delta_L_prime = L2 - L1;
    float delta_C_prime = C2_prime - C1_prime;
    
    float delta_h_prime;
    if (C1_prime * C2_prime == 0.0f) {
        delta_h_prime = 0.0f;
    } else {
        float diff = h2_prime - h1_prime;
        if (std::abs(diff) <= 180.0f) {
            delta_h_prime = diff;
        } else if (diff > 180.0f) {
            delta_h_prime = diff - 360.0f;
        } else {
            delta_h_prime = diff + 360.0f;
        }
    }
    
    float delta_H_prime = 2.0f * std::sqrt(C1_prime * C2_prime) * 
                          std::sin(delta_h_prime * static_cast<float>(M_PI) / 360.0f);
    
    // 计算平均 L', C', h'
    float L_avg = (L1 + L2) / 2.0f;
    float C_avg_prime = (C1_prime + C2_prime) / 2.0f;
    
    float h_avg_prime;
    if (C1_prime * C2_prime == 0.0f) {
        h_avg_prime = h1_prime + h2_prime;
    } else {
        float sum = h1_prime + h2_prime;
        float diff = std::abs(h1_prime - h2_prime);
        if (diff <= 180.0f) {
            h_avg_prime = sum / 2.0f;
        } else if (sum < 360.0f) {
            h_avg_prime = (sum + 360.0f) / 2.0f;
        } else {
            h_avg_prime = (sum - 360.0f) / 2.0f;
        }
    }
    
    // 计算 T
    float h_rad = h_avg_prime * static_cast<float>(M_PI) / 180.0f;
    float T = 1.0f - 0.17f * std::cos(h_rad - static_cast<float>(M_PI) / 6.0f) +
              0.24f * std::cos(2.0f * h_rad) +
              0.32f * std::cos(3.0f * h_rad + static_cast<float>(M_PI) / 30.0f) -
              0.20f * std::cos(4.0f * h_rad - 1.099557f); // 63 degrees in radians
    
    // 计算其他参数
    float delta_theta = 30.0f * std::exp(-std::pow((h_avg_prime - 275.0f) / 25.0f, 2));
    float C_avg_prime7 = std::pow(C_avg_prime, 7);
    float R_C = 2.0f * std::sqrt(C_avg_prime7 / (C_avg_prime7 + 6103515625.0f));
    
    float L_avg_minus_50 = L_avg - 50.0f;
    float S_L = 1.0f + (0.015f * L_avg_minus_50 * L_avg_minus_50) / 
                       std::sqrt(20.0f + L_avg_minus_50 * L_avg_minus_50);
    float S_C = 1.0f + 0.045f * C_avg_prime;
    float S_H = 1.0f + 0.015f * C_avg_prime * T;
    
    float R_T = -std::sin(2.0f * delta_theta * static_cast<float>(M_PI) / 180.0f) * R_C;
    
    // 计算最终色差
    float delta_L = delta_L_prime / S_L;
    float delta_C = delta_C_prime / S_C;
    float delta_H = delta_H_prime / S_H;
    
    float delta_E = std::sqrt(delta_L * delta_L + delta_C * delta_C + delta_H * delta_H + 
                              R_T * delta_C * delta_H);
    
    return delta_E;
}

// ============================================================================
// K-Means 聚类（Lab 空间）
// ============================================================================

std::vector<Cluster> kmeans_lab(const std::vector<Lab>& pixels, int k = 8, int max_iters = 30) {
    if (pixels.empty() || k <= 0) {
        return {};
    }
    
    std::vector<Lab> centroids;
    centroids.reserve(k);
    
    // 随机初始化聚类中心
    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_int_distribution<size_t> dist(0, pixels.size() - 1);
    
    for (int i = 0; i < k; ++i) {
        centroids.push_back(pixels[dist(gen)]);
    }
    
    std::vector<int> assignments(pixels.size());
    std::vector<size_t> cluster_sizes(k);
    
    for (int iter = 0; iter < max_iters; ++iter) {
        // 分配像素到最近的聚类中心
        #ifdef _OPENMP
        #pragma omp parallel for
        #endif
        for (size_t i = 0; i < pixels.size(); ++i) {
            float min_dist = std::numeric_limits<float>::max();
            int closest = 0;
            
            for (int j = 0; j < k; ++j) {
                float dist = ciede2000(pixels[i], centroids[j]);
                if (dist < min_dist) {
                    min_dist = dist;
                    closest = j;
                }
            }
            assignments[i] = closest;
        }
        
        // 更新聚类中心
        std::vector<Lab> new_centroids(k);
        std::fill(cluster_sizes.begin(), cluster_sizes.end(), 0);
        
        for (size_t i = 0; i < pixels.size(); ++i) {
            int cluster = assignments[i];
            new_centroids[cluster].L += pixels[i].L;
            new_centroids[cluster].a += pixels[i].a;
            new_centroids[cluster].b += pixels[i].b;
            cluster_sizes[cluster]++;
        }
        
        for (int j = 0; j < k; ++j) {
            if (cluster_sizes[j] > 0) {
                new_centroids[j].L /= cluster_sizes[j];
                new_centroids[j].a /= cluster_sizes[j];
                new_centroids[j].b /= cluster_sizes[j];
            } else {
                // 空聚类，随机选择一个新的中心
                new_centroids[j] = pixels[dist(gen)];
            }
        }
        
        // 检查收敛
        bool converged = true;
        for (int j = 0; j < k; ++j) {
            if (ciede2000(centroids[j], new_centroids[j]) > 1.0f) {
                converged = false;
                break;
            }
        }
        
        centroids = new_centroids;
        
        if (converged) {
            break;
        }
    }
    
    // 构建结果
    std::vector<Cluster> result;
    result.reserve(k);
    for (int j = 0; j < k; ++j) {
        result.emplace_back(centroids[j], cluster_sizes[j]);
    }
    
    return result;
}

// ============================================================================
// stb_image 头文件（用于图像解码）
// ============================================================================

#define STB_IMAGE_IMPLEMENTATION
#define STBI_ONLY_JPEG
#define STBI_ONLY_PNG
#define STBI_ONLY_BMP
#define STBI_ONLY_GIF

// 简化的 stb_image 声明（实际使用时应该包含完整的 stb_image.h）
// 这里我们使用 pybind11 的 buffer 协议来接收已经解码的图像数据

// ============================================================================
// 主提取函数
// ============================================================================

std::vector<std::tuple<uint8_t, uint8_t, uint8_t>> extract_colors(
    py::bytes image_data,
    int num_colors = 5,
    float min_distance = 20.0f,
    int max_image_size = 150
) {
    // 获取图像数据的指针和大小
    py::buffer_info info(py::buffer(image_data).request());
    const uint8_t* data = static_cast<const uint8_t*>(info.ptr);
    size_t data_size = info.size;
    
    if (data_size == 0) {
        throw std::invalid_argument("图像数据为空");
    }
    
    // 这里我们假设输入的图像数据已经被解码为 RGB/RGBA 格式
    // 实际实现中，可以使用 stb_image 或其他库来解码 JPEG/PNG 等格式
    // 为了简化，我们期望 Python 层先解码图像，然后传递原始像素数据
    
    // 注意：由于 pybind11 的 bytes 对象传递的是原始字节，
    // 我们需要 Python 层先将图像解码并传递像素数据
    
    // 这里我们处理的是已经解码的 RGB 像素数据
    // 假设数据格式为：前4个字节是宽度，接下来4个字节是高度，然后是 RGB 像素数据
    if (data_size < 8) {
        throw std::invalid_argument("图像数据格式无效");
    }
    
    int width = *reinterpret_cast<const int*>(data);
    int height = *reinterpret_cast<const int*>(data + 4);
    const uint8_t* pixels = data + 8;
    size_t pixel_data_size = data_size - 8;
    
    if (width <= 0 || height <= 0) {
        throw std::invalid_argument("图像尺寸无效");
    }
    
    // 确定通道数（根据数据大小推断）
    int channels = static_cast<int>(pixel_data_size / (width * height));
    if (channels != 3 && channels != 4) {
        throw std::invalid_argument("不支持的图像格式（需要 RGB 或 RGBA）");
    }
    
    // 缩放图像
    int target_width = std::min(width, max_image_size);
    int target_height = std::min(height, max_image_size);
    
    // 简单的最近邻缩放
    std::vector<RGB> scaled_pixels;
    scaled_pixels.reserve(target_width * target_height);
    
    for (int y = 0; y < target_height; ++y) {
        for (int x = 0; x < target_width; ++x) {
            int src_x = x * width / target_width;
            int src_y = y * height / target_height;
            int src_idx = (src_y * width + src_x) * channels;
            
            uint8_t r = pixels[src_idx];
            uint8_t g = pixels[src_idx + 1];
            uint8_t b = pixels[src_idx + 2];
            
            // 如果是 RGBA，检查透明度
            if (channels == 4) {
                uint8_t a = pixels[src_idx + 3];
                if (a < 128) {
                    continue;  // 跳过透明像素
                }
            }
            
            // 过滤掉接近黑色或白色的像素
            int brightness = (r + g + b) / 3;
            if (brightness > 240 || brightness < 20) {
                continue;
            }
            
            scaled_pixels.emplace_back(r, g, b);
        }
    }
    
    if (scaled_pixels.size() < 10) {
        throw std::runtime_error("有效像素数量不足");
    }
    
    // 随机采样以减少计算量
    if (scaled_pixels.size() > 5000) {
        std::random_device rd;
        std::mt19937 gen(rd());
        std::shuffle(scaled_pixels.begin(), scaled_pixels.end(), gen);
        scaled_pixels.resize(5000);
    }
    
    // 转换为 Lab 空间
    std::vector<Lab> lab_pixels;
    lab_pixels.reserve(scaled_pixels.size());
    
    for (const auto& rgb : scaled_pixels) {
        lab_pixels.push_back(rgb_to_lab(rgb.r, rgb.g, rgb.b));
    }
    
    // K-Means 聚类
    auto clusters = kmeans_lab(lab_pixels, 8, 30);
    
    // 按聚类大小排序
    std::sort(clusters.begin(), clusters.end(), 
              [](const Cluster& a, const Cluster& b) {
                  return a.size > b.size;
              });
    
    // 使用 CIEDE2000 筛选差异明显的颜色
    std::vector<Lab> selected_colors;
    selected_colors.reserve(num_colors);
    
    for (const auto& cluster : clusters) {
        if (selected_colors.size() >= static_cast<size_t>(num_colors)) {
            break;
        }
        
        bool is_different = true;
        for (const auto& selected : selected_colors) {
            float delta_e = ciede2000(cluster.centroid, selected);
            if (delta_e < min_distance) {
                is_different = false;
                break;
            }
        }
        
        if (is_different) {
            selected_colors.push_back(cluster.centroid);
        }
    }
    
    // 如果选不够，降低阈值继续选择
    if (selected_colors.size() < static_cast<size_t>(num_colors)) {
        for (const auto& cluster : clusters) {
            if (selected_colors.size() >= static_cast<size_t>(num_colors)) {
                break;
            }
            
            bool already_selected = false;
            for (const auto& selected : selected_colors) {
                if (ciede2000(cluster.centroid, selected) < 0.1f) {
                    already_selected = true;
                    break;
                }
            }
            
            if (!already_selected) {
                // 检查与已选颜色的差异（使用更低的阈值）
                bool is_different = true;
                for (const auto& selected : selected_colors) {
                    float delta_e = ciede2000(cluster.centroid, selected);
                    if (delta_e < 10.0f) {
                        is_different = false;
                        break;
                    }
                }
                
                if (is_different) {
                    selected_colors.push_back(cluster.centroid);
                }
            }
        }
    }
    
    // 如果仍然不足，生成互补色
    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_real_distribution<float> dist_L(20.0f, 80.0f);
    std::uniform_real_distribution<float> dist_ab(-100.0f, 100.0f);
    std::uniform_real_distribution<float> dist_perturb(-30.0f, 30.0f);
    
    while (selected_colors.size() < static_cast<size_t>(num_colors)) {
        Lab new_lab;
        
        if (selected_colors.empty()) {
            new_lab = Lab(dist_L(gen), dist_ab(gen), dist_ab(gen));
        } else {
            // 计算已有颜色的平均值并取反
            float avg_L = 0, avg_a = 0, avg_b = 0;
            for (const auto& c : selected_colors) {
                avg_L += c.L;
                avg_a += c.a;
                avg_b += c.b;
            }
            avg_L /= selected_colors.size();
            avg_a /= selected_colors.size();
            avg_b /= selected_colors.size();
            
            new_lab = Lab(100.0f - avg_L, -avg_a, -avg_b);
        }
        
        // 验证差异性
        bool is_different = true;
        for (const auto& selected : selected_colors) {
            if (ciede2000(new_lab, selected) < min_distance) {
                is_different = false;
                break;
            }
        }
        
        if (is_different) {
            selected_colors.push_back(new_lab);
        } else {
            // 添加扰动
            Lab perturbed(
                std::max(0.0f, std::min(100.0f, new_lab.L + dist_perturb(gen))),
                std::max(-128.0f, std::min(127.0f, new_lab.a + dist_perturb(gen) * 1.5f)),
                std::max(-128.0f, std::min(127.0f, new_lab.b + dist_perturb(gen) * 1.5f))
            );
            selected_colors.push_back(perturbed);
        }
    }
    
    // 转换为 RGB 并返回
    std::vector<std::tuple<uint8_t, uint8_t, uint8_t>> result;
    result.reserve(num_colors);
    
    for (size_t i = 0; i < static_cast<size_t>(num_colors) && i < selected_colors.size(); ++i) {
        RGB rgb = lab_to_rgb(selected_colors[i]);
        result.emplace_back(rgb.r, rgb.g, rgb.b);
    }
    
    return result;
}

// 处理 numpy 数组输入的版本
std::vector<std::tuple<uint8_t, uint8_t, uint8_t>> extract_colors_from_numpy(
    py::array_t<uint8_t> image_array,
    int num_colors = 5,
    float min_distance = 20.0f
) {
    py::buffer_info info = image_array.request();
    
    if (info.ndim != 3) {
        throw std::invalid_argument("图像数组必须是 3 维 (H, W, C)");
    }
    
    int height = info.shape[0];
    int width = info.shape[1];
    int channels = info.shape[2];
    
    if (channels != 3 && channels != 4) {
        throw std::invalid_argument("图像必须是 RGB 或 RGBA 格式");
    }
    
    const uint8_t* pixels = static_cast<const uint8_t*>(info.ptr);
    
    // 收集有效像素
    std::vector<Lab> lab_pixels;
    lab_pixels.reserve(width * height);
    
    for (int y = 0; y < height; y += std::max(1, height / 150)) {
        for (int x = 0; x < width; x += std::max(1, width / 150)) {
            int idx = (y * width + x) * channels;
            
            uint8_t r = pixels[idx];
            uint8_t g = pixels[idx + 1];
            uint8_t b = pixels[idx + 2];
            
            // 检查透明度
            if (channels == 4) {
                uint8_t a = pixels[idx + 3];
                if (a < 128) continue;
            }
            
            // 过滤黑白像素
            int brightness = (r + g + b) / 3;
            if (brightness > 240 || brightness < 20) continue;
            
            lab_pixels.push_back(rgb_to_lab(r, g, b));
        }
    }
    
    if (lab_pixels.size() < 10) {
        throw std::runtime_error("有效像素数量不足");
    }
    
    // 随机采样
    if (lab_pixels.size() > 5000) {
        std::random_device rd;
        std::mt19937 gen(rd());
        std::shuffle(lab_pixels.begin(), lab_pixels.end(), gen);
        lab_pixels.resize(5000);
    }
    
    // K-Means 聚类
    auto clusters = kmeans_lab(lab_pixels, 8, 30);
    
    // 按大小排序
    std::sort(clusters.begin(), clusters.end(), 
              [](const Cluster& a, const Cluster& b) { return a.size > b.size; });
    
    // 筛选颜色
    std::vector<Lab> selected_colors;
    selected_colors.reserve(num_colors);
    
    for (const auto& cluster : clusters) {
        if (selected_colors.size() >= static_cast<size_t>(num_colors)) break;
        
        bool is_different = true;
        for (const auto& selected : selected_colors) {
            if (ciede2000(cluster.centroid, selected) < min_distance) {
                is_different = false;
                break;
            }
        }
        
        if (is_different) {
            selected_colors.push_back(cluster.centroid);
        }
    }
    
    // 补充颜色
    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_real_distribution<float> dist_perturb(-30.0f, 30.0f);
    
    while (selected_colors.size() < static_cast<size_t>(num_colors)) {
        float avg_L = 0, avg_a = 0, avg_b = 0;
        for (const auto& c : selected_colors) {
            avg_L += c.L; avg_a += c.a; avg_b += c.b;
        }
        avg_L /= selected_colors.size();
        avg_a /= selected_colors.size();
        avg_b /= selected_colors.size();
        
        Lab new_lab(
            std::max(0.0f, std::min(100.0f, 100.0f - avg_L + dist_perturb(gen))),
            std::max(-128.0f, std::min(127.0f, -avg_a + dist_perturb(gen) * 1.5f)),
            std::max(-128.0f, std::min(127.0f, -avg_b + dist_perturb(gen) * 1.5f))
        );
        
        selected_colors.push_back(new_lab);
    }
    
    // 转换为 RGB
    std::vector<std::tuple<uint8_t, uint8_t, uint8_t>> result;
    result.reserve(num_colors);
    
    for (int i = 0; i < num_colors; ++i) {
        RGB rgb = lab_to_rgb(selected_colors[i]);
        result.emplace_back(rgb.r, rgb.g, rgb.b);
    }
    
    return result;
}

// ============================================================================
// pybind11 模块定义
// ============================================================================

PYBIND11_MODULE(color_extractor_cpp, m) {
    m.doc() = "C++ 实现的高性能封面颜色提取器";
    
    m.attr("__version__") = VERSION;
    
    m.def("extract_colors", &extract_colors,
          "从图像数据中提取主色调",
          py::arg("image_data"),
          py::arg("num_colors") = 5,
          py::arg("min_distance") = 20.0f,
          py::arg("max_image_size") = 150);
    
    m.def("extract_colors_from_numpy", &extract_colors_from_numpy,
          "从 numpy 数组中提取主色调",
          py::arg("image_array"),
          py::arg("num_colors") = 5,
          py::arg("min_distance") = 20.0f);
    
    m.def("rgb_to_lab", [](uint8_t r, uint8_t g, uint8_t b) -> std::tuple<float, float, float> {
        Lab lab = rgb_to_lab(r, g, b);
        return std::make_tuple(lab.L, lab.a, lab.b);
    }, "RGB 转 Lab", py::arg("r"), py::arg("g"), py::arg("b"));
    
    m.def("lab_to_rgb", [](float L, float a, float b) -> std::tuple<uint8_t, uint8_t, uint8_t> {
        RGB rgb = lab_to_rgb(Lab(L, a, b));
        return std::make_tuple(rgb.r, rgb.g, rgb.b);
    }, "Lab 转 RGB", py::arg("L"), py::arg("a"), py::arg("b"));
    
    m.def("ciede2000", [](float L1, float a1, float b1, float L2, float a2, float b2) -> float {
        return ciede2000(Lab(L1, a1, b1), Lab(L2, a2, b2));
    }, "计算 CIEDE2000 色差", 
          py::arg("L1"), py::arg("a1"), py::arg("b1"),
          py::arg("L2"), py::arg("a2"), py::arg("b2"));
}
