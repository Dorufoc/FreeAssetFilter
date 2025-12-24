#pragma once

#include <string>
#include <iostream>

enum class LogLevel {
    DEBUG,
    INFO,
    WARNING,
    ERROR,
    CRITICAL
};

class Logger {
public:
    static Logger& GetInstance();
    
    void SetLogLevel(LogLevel level);
    void SetLogFile(const std::string& filename);
    
    void Debug(const std::string& message);
    void Info(const std::string& message);
    void Warning(const std::string& message);
    void Error(const std::string& message);
    void Critical(const std::string& message);
    
private:
    Logger();
    ~Logger();
    
    LogLevel current_level_;
    std::ostream* log_stream_;
    bool own_stream_;
    
    std::string GetLevelString(LogLevel level) const;
    void Log(LogLevel level, const std::string& message);
};

// Logger macros for easy usage
#define LOG_DEBUG(msg) Logger::GetInstance().Debug(msg)
#define LOG_INFO(msg) Logger::GetInstance().Info(msg)
#define LOG_WARNING(msg) Logger::GetInstance().Warning(msg)
#define LOG_ERROR(msg) Logger::GetInstance().Error(msg)
#define LOG_CRITICAL(msg) Logger::GetInstance().Critical(msg)
