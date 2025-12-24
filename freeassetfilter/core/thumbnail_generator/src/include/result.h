#pragma once

#include <string>
#include <vector>
#include "processor.h"

class ResultFormatter {
public:
    static std::string FormatAsJson(const std::vector<ThumbnailResult>& results);
    static std::string FormatAsText(const std::vector<ThumbnailResult>& results);
    static std::string FormatAsCsv(const std::vector<ThumbnailResult>& results);
};
