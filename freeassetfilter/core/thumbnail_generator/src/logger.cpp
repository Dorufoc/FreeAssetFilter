#include "include/logger.h"
#include <fstream>
#include <chrono>
#include <iomanip>
#include <sstream>

Logger::Logger() : current_level_(LogLevel::INFO), log_stream_(&std::cout), own_stream_(false) {}

Logger::~Logger() {
    if (own_stream_ && log_stream_ != &std::cout && log_stream_ != &std::cerr) {
        delete log_stream_;
    }
}

Logger& Logger::GetInstance() {
    static Logger instance;
    return instance;
}

void Logger::SetLogLevel(LogLevel level) {
    current_level_ = level;
}

void Logger::SetLogFile(const std::string& filename) {
    if (own_stream_ && log_stream_ != &std::cout && log_stream_ != &std::cerr) {
        delete log_stream_;
    }
    
    log_stream_ = new std::ofstream(filename, std::ios::app);
    own_stream_ = true;
    
    if (!static_cast<std::ofstream*>(log_stream_)->is_open()) {
        std::cerr << "Failed to open log file: " << filename << std::endl;
        delete log_stream_;
        log_stream_ = &std::cout;
        own_stream_ = false;
    }
}

std::string Logger::GetLevelString(LogLevel level) const {
    switch (level) {
        case LogLevel::DEBUG: return "DEBUG";
        case LogLevel::INFO: return "INFO";
        case LogLevel::WARNING: return "WARNING";
        case LogLevel::ERROR: return "ERROR";
        case LogLevel::CRITICAL: return "CRITICAL";
        default: return "UNKNOWN";
    }
}

void Logger::Log(LogLevel level, const std::string& message) {
    if (level < current_level_) {
        return;
    }
    
    auto now = std::chrono::system_clock::now();
    auto now_time = std::chrono::system_clock::to_time_t(now);
    auto now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()) % 1000;
    
    std::tm local_tm = *std::localtime(&now_time);
    
    std::stringstream ss;
    ss << std::put_time(&local_tm, "%Y-%m-%d %H:%M:%S") << "." << std::setfill('0') << std::setw(3) << now_ms.count() << " ";
    ss << "[" << GetLevelString(level) << "] " << message << std::endl;
    
    *log_stream_ << ss.str();
    log_stream_->flush();
}

void Logger::Debug(const std::string& message) {
    Log(LogLevel::DEBUG, message);
}

void Logger::Info(const std::string& message) {
    Log(LogLevel::INFO, message);
}

void Logger::Warning(const std::string& message) {
    Log(LogLevel::WARNING, message);
}

void Logger::Error(const std::string& message) {
    Log(LogLevel::ERROR, message);
}

void Logger::Critical(const std::string& message) {
    Log(LogLevel::CRITICAL, message);
}
