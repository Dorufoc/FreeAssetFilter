#pragma once

#include <string>
#include <vector>

/**
 * @struct ProcessingConfig
 * @brief Configuration parameters for thumbnail generation
 * 
 * This struct holds all the configuration parameters needed for generating thumbnails,
 * including input/output directories, dimensions, quality settings, and threading options.
 */
struct ProcessingConfig {
    std::string input_dir;      /**< Input directory containing images to process */
    std::string output_dir;     /**< Output directory for generated thumbnails */
    int max_width;              /**< Maximum width of generated thumbnails */
    int max_height;             /**< Maximum height of generated thumbnails */
    int threads;                /**< Number of concurrent threads to use */
    int quality;                /**< Output image quality (0-100) */
    std::string output_format;  /**< Output image format (jpg, png, webp, etc.) */
    std::string return_format;  /**< Result output format (json, text, csv) */
    bool verbose;               /**< Enable verbose logging */
    
    /**
     * @brief Default constructor with sensible default values
     */
    ProcessingConfig() :
        max_width(256),
        max_height(256),
        threads(4),
        quality(85),
        output_format("jpg"),
        return_format("json"),
        verbose(false) {}
};

/**
 * @struct ThumbnailResult
 * @brief Result of processing a single image
 * 
 * This struct holds the results of processing a single image, including
 * whether processing was successful, filenames, paths, and error messages.
 */
struct ThumbnailResult {
    std::string original_filename;    /**< Original image filename */
    std::string thumbnail_filename;   /**< Generated thumbnail filename */
    std::string thumbnail_path;       /**< Full path to the generated thumbnail */
    bool success;                     /**< Whether the processing was successful */
    std::string error_message;        /**< Error message if processing failed */
    
    /**
     * @brief Default constructor
     */
    ThumbnailResult() : success(false) {}
};

/**
 * @class ThumbnailProcessor
 * @brief Main thumbnail generation processor class
 * 
 * This class handles the core functionality of generating thumbnails from images,
 * including file discovery, concurrent processing, and result generation.
 */
class ThumbnailProcessor {
public:
    /**
     * @brief Constructor with configuration
     * @param config Processing configuration parameters
     */
    explicit ThumbnailProcessor(const ProcessingConfig& config);
    
    /**
     * @brief Destructor
     */
    ~ThumbnailProcessor();
    
    /**
     * @brief Process all images in the input directory
     * @return Vector of processing results for each image
     */
    std::vector<ThumbnailResult> ProcessAll();
    
    /**
     * @brief Process a single image file
     * @param input_path Path to the input image file
     * @return Result of processing the image
     */
    ThumbnailResult ProcessSingleImage(const std::string& input_path);
    
private:
    /**
     * @brief Get list of image files in the specified directory
     * @param dir Directory to search for image files
     * @return Vector of paths to image files
     */
    std::vector<std::string> GetImageFiles(const std::string& dir);
    
    /**
     * @brief Check if a filename corresponds to a supported image format
     * @param filename Filename to check
     * @return True if the file is a supported image format, false otherwise
     */
    bool IsSupportedImage(const std::string& filename);
    
    ProcessingConfig config_;  /**< Processing configuration */
};
