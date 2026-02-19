// lut_preview.cpp
// C++ 实现的高性能 LUT 预览生成器
// 使用 pybind11 绑定到 Python

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>

#include <vector>
#include <cmath>
#include <algorithm>
#include <fstream>
#include <sstream>
#include <string>
#include <cstring>
#include <stdexcept>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

#ifdef _OPENMP
#include <omp.h>
#endif

#define VERSION "1.0.0"

namespace py = pybind11;

// ============================================================================
// CRC32 查找表
// ============================================================================

uint32_t crc_table[256];
bool crc_initialized = false;

void init_crc_table() {
    if (crc_initialized) return;
    for (uint32_t i = 0; i < 256; i++) {
        uint32_t c = i;
        for (int j = 0; j < 8; j++) {
            c = (c & 1) ? (0xEDB88320 ^ (c >> 1)) : (c >> 1);
        }
        crc_table[i] = c;
    }
    crc_initialized = true;
}

uint32_t calculate_crc32(const std::vector<uint8_t>& data) {
    uint32_t crc = 0xFFFFFFFF;
    for (size_t i = 0; i < data.size(); i++) {
        crc = crc_table[(crc ^ data[i]) & 0xFF] ^ (crc >> 8);
    }
    return crc ^ 0xFFFFFFFF;
}

// PNG 辅助函数 - 使用固定 CRC
uint32_t get_chunk_crc(const char* type, const std::vector<uint8_t>& data) {
    std::vector<uint8_t> crc_data;
    crc_data.insert(crc_data.end(), type, type + 4);
    crc_data.insert(crc_data.end(), data.begin(), data.end());
    return calculate_crc32(crc_data);
}

// ============================================================================
// 数据结构定义
// ============================================================================

struct LUTData {
    bool is_3d;
    std::string title;
    int size;
    std::vector<float> data_3d;
    std::vector<float> data_1d;

    LUTData() : is_3d(true), size(0) {}

    bool is_valid() const {
        if (is_3d) {
            return size > 0 && data_3d.size() == static_cast<size_t>(size * size * size) * 3;
        } else {
            return size > 0 && data_1d.size() == static_cast<size_t>(size) * 3;
        }
    }
};

// ============================================================================
// PNG 编码
// ============================================================================

void write_chunk(std::vector<uint8_t>& buffer, const char* type, const std::vector<uint8_t>& data) {
    uint32_t length = data.size();

    // 写入长度
    buffer.push_back((length >> 24) & 0xFF);
    buffer.push_back((length >> 16) & 0xFF);
    buffer.push_back((length >> 8) & 0xFF);
    buffer.push_back(length & 0xFF);

    // 写入类型
    buffer.insert(buffer.end(), type, type + 4);

    // 写入数据
    if (!data.empty()) {
        buffer.insert(buffer.end(), data.begin(), data.end());
    }

    // 计算并写入 CRC（包括 type 和 data）
    uint32_t crc = get_chunk_crc(type, data);
    buffer.push_back((crc >> 24) & 0xFF);
    buffer.push_back((crc >> 16) & 0xFF);
    buffer.push_back((crc >> 8) & 0xFF);
    buffer.push_back(crc & 0xFF);
}

void write_png_to_buffer(const uint8_t* image_data, int width, int height,
                         std::vector<uint8_t>& buffer) {
    const uint8_t png_signature[] = {0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A};
    buffer.insert(buffer.end(), png_signature, png_signature + 8);

    std::vector<uint8_t> ihdr_data(13);
    ihdr_data[0] = (width >> 24) & 0xFF;
    ihdr_data[1] = (width >> 16) & 0xFF;
    ihdr_data[2] = (width >> 8) & 0xFF;
    ihdr_data[3] = width & 0xFF;
    ihdr_data[4] = (height >> 24) & 0xFF;
    ihdr_data[5] = (height >> 16) & 0xFF;
    ihdr_data[6] = (height >> 8) & 0xFF;
    ihdr_data[7] = height & 0xFF;
    ihdr_data[8] = 8;
    ihdr_data[9] = 2;
    ihdr_data[10] = 0;
    ihdr_data[11] = 0;
    ihdr_data[12] = 0;

    write_chunk(buffer, "IHDR", ihdr_data);

    std::vector<uint8_t> raw_data;
    raw_data.reserve(height * (1 + width * 3));
    for (int y = 0; y < height; y++) {
        raw_data.push_back(0);
        for (int x = 0; x < width; x++) {
            int idx = (y * width + x) * 3;
            raw_data.push_back(image_data[idx]);
            raw_data.push_back(image_data[idx + 1]);
            raw_data.push_back(image_data[idx + 2]);
        }
    }

    std::vector<uint8_t> compressed;
    compressed.push_back(0x78);
    compressed.push_back(0x01);

    const size_t max_block_size = 65535;
    size_t pos = 0;
    while (pos < raw_data.size()) {
        size_t block_size = std::min(raw_data.size() - pos, max_block_size);
        bool is_last = (pos + block_size >= raw_data.size());

        compressed.push_back(is_last ? 0x01 : 0x00);
        compressed.push_back(block_size & 0xFF);
        compressed.push_back((block_size >> 8) & 0xFF);
        compressed.push_back((~block_size) & 0xFF);
        compressed.push_back((~block_size >> 8) & 0xFF);

        compressed.insert(compressed.end(), raw_data.begin() + pos, raw_data.begin() + pos + block_size);
        pos += block_size;
    }

    uint32_t a = 1, b = 0;
    for (size_t i = 0; i < raw_data.size(); i++) {
        a = (a + raw_data[i]) % 65521;
        b = (b + a) % 65521;
    }
    uint32_t adler = (b << 16) | a;
    compressed.push_back((adler >> 24) & 0xFF);
    compressed.push_back((adler >> 16) & 0xFF);
    compressed.push_back((adler >> 8) & 0xFF);
    compressed.push_back(adler & 0xFF);

    write_chunk(buffer, "IDAT", compressed);

    write_chunk(buffer, "IEND", std::vector<uint8_t>());
}

// ============================================================================
// LUT 解析器
// ============================================================================

bool parse_cube_data(const std::vector<std::string>& lines, LUTData& lut) {
    lut.is_3d = true;
    lut.size = 0;
    int data_start = 0;

    // 解析头部信息
    for (int i = 0; i < (int)lines.size(); i++) {
        std::string trimmed = lines[i];
        
        // 使用 find_first_not_of 来 trim
        size_t start = trimmed.find_first_not_of(" \t\r\n");
        if (start == std::string::npos) continue;
        size_t end = trimmed.find_last_not_of(" \t\r\n");
        trimmed = trimmed.substr(start, end - start + 1);
        
        if (trimmed.empty() || trimmed[0] == '#') {
            continue;
        }
        
        // 解析 TITLE
        if (trimmed.rfind("TITLE", 0) == 0) {
            size_t pos1 = trimmed.find('"');
            size_t pos2 = trimmed.find('"', pos1 + 1);
            if (pos1 != std::string::npos && pos2 != std::string::npos) {
                lut.title = trimmed.substr(pos1 + 1, pos2 - pos1 - 1);
            }
            continue;
        }
        
        // 解析 LUT_3D_SIZE
        if (trimmed.rfind("LUT_3D_SIZE", 0) == 0) {
            lut.is_3d = true;
            std::istringstream iss(trimmed);
            std::string word;
            std::string last_word;
            while (iss >> word) {
                last_word = word;
            }
            lut.size = std::stoi(last_word);
            continue;
        }
        
        // 解析 LUT_1D_SIZE
        if (trimmed.rfind("LUT_1D_SIZE", 0) == 0) {
            lut.is_3d = false;
            std::istringstream iss(trimmed);
            std::string word;
            std::string last_word;
            while (iss >> word) {
                last_word = word;
            }
            lut.size = std::stoi(last_word);
            continue;
        }
        
        // 检查是否是数据行
        std::istringstream iss(trimmed);
        float r, g, b;
        if (iss >> r >> g >> b) {
            data_start = i;
            break;
        }
    }

    // 解析数据
    for (int i = data_start; i < (int)lines.size(); i++) {
        std::string trimmed = lines[i];
        
        size_t start = trimmed.find_first_not_of(" \t\r\n");
        if (start == std::string::npos) continue;
        size_t end = trimmed.find_last_not_of(" \t\r\n");
        trimmed = trimmed.substr(start, end - start + 1);
        
        if (trimmed.empty() || trimmed[0] == '#') {
            continue;
        }
        
        std::istringstream iss(trimmed);
        float r, g, b;
        if (iss >> r >> g >> b) {
            if (lut.is_3d) {
                lut.data_3d.push_back(r);
                lut.data_3d.push_back(g);
                lut.data_3d.push_back(b);
            } else {
                lut.data_1d.push_back(r);
                lut.data_1d.push_back(g);
                lut.data_1d.push_back(b);
            }
        }
    }

    if (!lut.is_3d && lut.data_3d.size() > 0) {
        lut.data_1d = lut.data_3d;
        lut.data_3d.clear();
    }

    return lut.is_valid();
}

bool parse_cube_file(const std::string& file_path, LUTData& lut) {
    // 让 Python 端读取文件内容然后调用 parse_cube_data
    // 这里我们用 ifstream 尝试打开
    std::ifstream file(file_path);
    if (!file.is_open()) {
        return false;
    }

    std::vector<std::string> lines;
    std::string line;
    while (std::getline(file, line)) {
        lines.push_back(line);
    }
    file.close();
    
    return parse_cube_data(lines, lut);
}

// ============================================================================
// LUT 应用算法
// ============================================================================

inline float clamp01(float v) {
    return std::max(0.0f, std::min(1.0f, v));
}

inline void apply_3d_lut(const LUTData& lut, float r, float g, float b, float& out_r, float& out_g, float& out_b) {
    if (!lut.is_valid()) {
        out_r = r; out_g = g; out_b = b;
        return;
    }

    int size = lut.size;
    float rf = clamp01(r) * (size - 1);
    float gf = clamp01(g) * (size - 1);
    float bf = clamp01(b) * (size - 1);

    int r0 = static_cast<int>(rf);
    int g0 = static_cast<int>(gf);
    int b0 = static_cast<int>(bf);

    int r1 = std::min(r0 + 1, size - 1);
    int g1 = std::min(g0 + 1, size - 1);
    int b1 = std::min(b0 + 1, size - 1);

    float dr = rf - r0;
    float dg = gf - g0;
    float db = bf - b0;

    auto get_val = [&lut, size](int r, int g, int b, int channel) -> float {
        int idx = (b * size + g) * size + r;
        idx = idx * 3 + channel;
        if (idx >= 0 && idx < static_cast<int>(lut.data_3d.size())) {
            return lut.data_3d[idx];
        }
        return 0.0f;
    };

    float c000_r = get_val(r0, g0, b0, 0), c000_g = get_val(r0, g0, b0, 1), c000_b = get_val(r0, g0, b0, 2);
    float c001_r = get_val(r0, g0, b1, 0), c001_g = get_val(r0, g0, b1, 1), c001_b = get_val(r0, g0, b1, 2);
    float c010_r = get_val(r0, g1, b0, 0), c010_g = get_val(r0, g1, b0, 1), c010_b = get_val(r0, g1, b0, 2);
    float c011_r = get_val(r0, g1, b1, 0), c011_g = get_val(r0, g1, b1, 1), c011_b = get_val(r0, g1, b1, 2);
    float c100_r = get_val(r1, g0, b0, 0), c100_g = get_val(r1, g0, b0, 1), c100_b = get_val(r1, g0, b0, 2);
    float c101_r = get_val(r1, g0, b1, 0), c101_g = get_val(r1, g0, b1, 1), c101_b = get_val(r1, g0, b1, 2);
    float c110_r = get_val(r1, g1, b0, 0), c110_g = get_val(r1, g1, b0, 1), c110_b = get_val(r1, g1, b0, 2);
    float c111_r = get_val(r1, g1, b1, 0), c111_g = get_val(r1, g1, b1, 1), c111_b = get_val(r1, g1, b1, 2);

    float one_dr = 1.0f - dr;
    float one_dg = 1.0f - dg;
    float one_db = 1.0f - db;

    out_r = c000_r * one_dr * one_dg * one_db + c001_r * one_dr * one_dg * db +
            c010_r * one_dr * dg * one_db + c011_r * one_dr * dg * db +
            c100_r * dr * one_dg * one_db + c101_r * dr * one_dg * db +
            c110_r * dr * dg * one_db + c111_r * dr * dg * db;

    out_g = c000_g * one_dr * one_dg * one_db + c001_g * one_dr * one_dg * db +
            c010_g * one_dr * dg * one_db + c011_g * one_dr * dg * db +
            c100_g * dr * one_dg * one_db + c101_g * dr * one_dg * db +
            c110_g * dr * dg * one_db + c111_g * dr * dg * db;

    out_b = c000_b * one_dr * one_dg * one_db + c001_b * one_dr * one_dg * db +
            c010_b * one_dr * dg * one_db + c011_b * one_dr * dg * db +
            c100_b * dr * one_dg * one_db + c101_b * dr * one_dg * db +
            c110_b * dr * dg * one_db + c111_b * dr * dg * db;
}

inline void apply_1d_lut(const LUTData& lut, float r, float g, float b, float& out_r, float& out_g, float& out_b) {
    if (!lut.is_valid()) {
        out_r = r; out_g = g; out_b = b;
        return;
    }

    int size = lut.size;

    auto interpolate = [&lut, size](float value, int offset) -> float {
        float idx_f = clamp01(value) * (size - 1);
        int idx0 = static_cast<int>(idx_f);
        int idx1 = std::min(idx0 + 1, size - 1);
        float t = idx_f - idx0;

        float v0 = lut.data_1d[idx0 * 3 + offset];
        float v1 = lut.data_1d[idx1 * 3 + offset];

        return v0 * (1.0f - t) + v1 * t;
    };

    out_r = interpolate(r, 0);
    out_g = interpolate(g, 1);
    out_b = interpolate(b, 2);
}

inline void apply_lut_pixel(const LUTData& lut, float r, float g, float b, float& out_r, float& out_g, float& out_b) {
    if (lut.is_3d) {
        apply_3d_lut(lut, r, g, b, out_r, out_g, out_b);
    } else {
        apply_1d_lut(lut, r, g, b, out_r, out_g, out_b);
    }
}

// ============================================================================
// 图像处理
// ============================================================================

void resize_image(const uint8_t* src, int src_width, int src_height,
                  uint8_t* dst, int dst_width, int dst_height) {
    float scale_x = static_cast<float>(src_width) / dst_width;
    float scale_y = static_cast<float>(src_height) / dst_height;

    #pragma omp parallel for schedule(dynamic)
    for (int y = 0; y < dst_height; y++) {
        float src_y = (y + 0.5f) * scale_y - 0.5f;
        int y0 = static_cast<int>(src_y);
        int y1 = std::min(y0 + 1, src_height - 1);
        float ty = src_y - y0;

        for (int x = 0; x < dst_width; x++) {
            float src_x = (x + 0.5f) * scale_x - 0.5f;
            int x0 = static_cast<int>(src_x);
            int x1 = std::min(x0 + 1, src_width - 1);
            float tx = src_x - x0;

            int dst_idx = (y * dst_width + x) * 3;

            for (int c = 0; c < 3; c++) {
                float v00 = src[(y0 * src_width + x0) * 3 + c];
                float v01 = src[(y0 * src_width + x1) * 3 + c];
                float v10 = src[(y1 * src_width + x0) * 3 + c];
                float v11 = src[(y1 * src_width + x1) * 3 + c];

                float v0 = v00 * (1.0f - tx) + v01 * tx;
                float v1 = v10 * (1.0f - tx) + v11 * tx;
                float v = v0 * (1.0f - ty) + v1 * ty;

                dst[dst_idx + c] = static_cast<uint8_t>(std::max(0.0f, std::min(255.0f, v)));
            }
        }
    }
}

void apply_lut_to_image(const LUTData& lut,
                        const uint8_t* src, int width, int height,
                        uint8_t* dst) {
    #pragma omp parallel for schedule(dynamic)
    for (int i = 0; i < width * height; i++) {
        int src_idx = i * 3;
        int dst_idx = i * 3;

        float r = src[src_idx] / 255.0f;
        float g = src[src_idx + 1] / 255.0f;
        float b = src[src_idx + 2] / 255.0f;

        float out_r, out_g, out_b;
        apply_lut_pixel(lut, r, g, b, out_r, out_g, out_b);

        dst[dst_idx] = static_cast<uint8_t>(std::max(0.0f, std::min(255.0f, out_r * 255.0f)));
        dst[dst_idx + 1] = static_cast<uint8_t>(std::max(0.0f, std::min(255.0f, out_g * 255.0f)));
        dst[dst_idx + 2] = static_cast<uint8_t>(std::max(0.0f, std::min(255.0f, out_b * 255.0f)));
    }
}

// ============================================================================
// 主生成函数
// ============================================================================

py::bytes generate_preview_from_data_impl(const std::string& lut_content,
                                         py::array_t<uint8_t> image_array,
                                         int output_width,
                                         int output_height) {
    init_crc_table();

    // 解析内容行为 lines
    std::vector<std::string> lines;
    std::string line;
    size_t pos = 0, newline_pos;
    while ((newline_pos = lut_content.find('\n', pos)) != std::string::npos) {
        line = lut_content.substr(pos, newline_pos - pos);
        lines.push_back(line);
        pos = newline_pos + 1;
    }
    if (pos < lut_content.size()) {
        lines.push_back(lut_content.substr(pos));
    }

    LUTData lut;
    if (!parse_cube_data(lines, lut)) {
        throw std::runtime_error("Failed to parse LUT data");
    }

    py::buffer_info buf = image_array.request();
    if (buf.ndim != 3) {
        throw std::runtime_error("Image array must be 3D (height, width, channels)");
    }

    int height = buf.shape[0];
    int width = buf.shape[1];
    int channels = buf.shape[2];

    if (channels != 3 && channels != 4) {
        throw std::runtime_error("Image must have 3 (RGB) or 4 (RGBA) channels");
    }

    const uint8_t* src_data = static_cast<const uint8_t*>(buf.ptr);

    std::vector<uint8_t> rgb_data;
    if (channels == 4) {
        rgb_data.resize(width * height * 3);
        #pragma omp parallel for schedule(dynamic)
        for (int i = 0; i < width * height; i++) {
            rgb_data[i * 3] = src_data[i * 4];
            rgb_data[i * 3 + 1] = src_data[i * 4 + 1];
            rgb_data[i * 3 + 2] = src_data[i * 4 + 2];
        }
        src_data = rgb_data.data();
    }

    std::vector<uint8_t> scaled_data(output_width * output_height * 3);
    resize_image(src_data, width, height, scaled_data.data(), output_width, output_height);

    std::vector<uint8_t> output_data(output_width * output_height * 3);
    apply_lut_to_image(lut, scaled_data.data(), output_width, output_height, output_data.data());

    std::vector<uint8_t> png_data;
    write_png_to_buffer(output_data.data(), output_width, output_height, png_data);

    return py::bytes(reinterpret_cast<const char*>(png_data.data()), png_data.size());
}

py::bytes generate_preview_from_array_impl(const std::string& lut_file_path,
                                           py::array_t<uint8_t> image_array,
                                           int output_width,
                                           int output_height) {
    init_crc_table();

    LUTData lut;
    if (!parse_cube_file(lut_file_path, lut)) {
        throw std::runtime_error("Failed to parse LUT file: " + lut_file_path);
    }

    py::buffer_info buf = image_array.request();
    if (buf.ndim != 3) {
        throw std::runtime_error("Image array must be 3D (height, width, channels)");
    }

    int height = buf.shape[0];
    int width = buf.shape[1];
    int channels = buf.shape[2];

    if (channels != 3 && channels != 4) {
        throw std::runtime_error("Image must have 3 (RGB) or 4 (RGBA) channels");
    }

    const uint8_t* src_data = static_cast<const uint8_t*>(buf.ptr);

    std::vector<uint8_t> rgb_data;
    if (channels == 4) {
        rgb_data.resize(width * height * 3);
        #pragma omp parallel for schedule(dynamic)
        for (int i = 0; i < width * height; i++) {
            rgb_data[i * 3] = src_data[i * 4];
            rgb_data[i * 3 + 1] = src_data[i * 4 + 1];
            rgb_data[i * 3 + 2] = src_data[i * 4 + 2];
        }
        src_data = rgb_data.data();
    }

    std::vector<uint8_t> scaled_data(output_width * output_height * 3);
    resize_image(src_data, width, height, scaled_data.data(), output_width, output_height);

    std::vector<uint8_t> output_data(output_width * output_height * 3);
    apply_lut_to_image(lut, scaled_data.data(), output_width, output_height, output_data.data());

    std::vector<uint8_t> png_data;
    write_png_to_buffer(output_data.data(), output_width, output_height, png_data);

    return py::bytes(reinterpret_cast<const char*>(png_data.data()), png_data.size());
}

// ============================================================================
// pybind11 模块定义
// ============================================================================

PYBIND11_MODULE(lut_preview_cpp, m) {
    m.doc() = "C++ 实现的高性能 LUT 预览生成器";

    // 接受 LUT 文件内容的版本
    m.def("generate_preview", [](const py::object& lut_content_or_path, py::array_t<uint8_t> image_array,
                                int output_width, int output_height) {
        // 尝试作为文件路径处理
        std::string path = lut_content_or_path.cast<std::string>();
        
        // 首先尝试解析为文件路径
        std::ifstream test_file(path);
        if (test_file.is_open()) {
            test_file.close();
            // 是有效文件路径，使用文件版本
            return generate_preview_from_array_impl(path, image_array, output_width, output_height);
        }
        
        // 否则尝试作为内容处理
        return generate_preview_from_data_impl(path, image_array, output_width, output_height);
    },
    "从 LUT 内容或路径生成预览图像",
    py::arg("lut_content_or_path"),
    py::arg("image_array"),
    py::arg("output_width"),
    py::arg("output_height"));

    // 直接接受内容的版本
    m.def("generate_preview_from_data", &generate_preview_from_data_impl,
          "从 LUT 内容生成预览图像",
          py::arg("lut_content"),
          py::arg("image_array"),
          py::arg("output_width"),
          py::arg("output_height"));

    m.attr("__version__") = VERSION;
}
