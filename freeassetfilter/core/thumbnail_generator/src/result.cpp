#include "include/result.h"
#include <sstream>
#include <iomanip>

// 简单的JSON格式化实现，用于生成结果输出
class SimpleJsonFormatter {
public:
    static std::string EscapeString(const std::string& str) {
        std::string escaped;
        for (char c : str) {
            switch (c) {
                case '"': escaped += "\\\""; break;
                case '\\': escaped += "\\\\"; break;
                case '\b': escaped += "\\b"; break;
                case '\f': escaped += "\\f"; break;
                case '\n': escaped += "\\n"; break;
                case '\r': escaped += "\\r"; break;
                case '\t': escaped += "\\t"; break;
                default:
                    if (c < 0x20 || c > 0x7E) {
                        // 转义非ASCII字符
                        char buffer[10];
                        snprintf(buffer, sizeof(buffer), "\\u%04x", static_cast<unsigned int>(static_cast<unsigned char>(c)));
                        escaped += buffer;
                    } else {
                        escaped += c;
                    }
                    break;
            }
        }
        return escaped;
    }
};

std::string ResultFormatter::FormatAsJson(const std::vector<ThumbnailResult>& results) {
    std::ostringstream oss;
    
    oss << "{\n";
    oss << "  \"results\": [\n";
    
    for (size_t i = 0; i < results.size(); ++i) {
        const auto& result = results[i];
        oss << "    {\n";
        oss << "      \"original_filename\": \"" << SimpleJsonFormatter::EscapeString(result.original_filename) << "\",\n";
        oss << "      \"thumbnail_filename\": \"" << SimpleJsonFormatter::EscapeString(result.thumbnail_filename) << "\",\n";
        oss << "      \"thumbnail_path\": \"" << SimpleJsonFormatter::EscapeString(result.thumbnail_path) << "\",\n";
        oss << "      \"success\": " << (result.success ? "true" : "false");
        
        if (!result.success) {
            oss << ",\n";
            oss << "      \"error_message\": \"" << SimpleJsonFormatter::EscapeString(result.error_message) << "\"";
        }
        
        oss << "\n";
        oss << "    }";
        
        if (i < results.size() - 1) {
            oss << ",";
        }
        oss << "\n";
    }
    
    oss << "  ]\n";
    oss << "}";
    
    return oss.str();
}

std::string ResultFormatter::FormatAsText(const std::vector<ThumbnailResult>& results) {
    std::ostringstream oss;
    
    oss << "Thumbnail Generation Results\n";
    oss << "================================\n";
    oss << std::left << std::setw(40) << "Original File" << std::setw(40) << "Thumbnail File" << std::setw(10) << "Status" << "Error\n";
    oss << std::string(120, '-') << "\n";
    
    for (const auto& result : results) {
        oss << std::left << std::setw(40) << result.original_filename.substr(0, 39) << " ";
        oss << std::setw(40) << (result.success ? result.thumbnail_filename.substr(0, 39) : "-") << " ";
        oss << std::setw(10) << (result.success ? "SUCCESS" : "FAILED") << " ";
        if (!result.success) {
            oss << result.error_message.substr(0, 30);
        }
        oss << "\n";
    }
    
    return oss.str();
}

std::string ResultFormatter::FormatAsCsv(const std::vector<ThumbnailResult>& results) {
    std::ostringstream oss;
    
    oss << "Original Filename,Thumbnail Filename,Thumbnail Path,Success,Error Message\n";
    
    for (const auto& result : results) {
        oss << '"' << result.original_filename << '","' 
            << result.thumbnail_filename << '","' 
            << result.thumbnail_path << '","' 
            << (result.success ? "true" : "false") << '","' 
            << result.error_message << '"\n';
    }
    
    return oss.str();
}
