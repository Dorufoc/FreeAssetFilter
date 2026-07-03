# FreeAssetFilter components module
# All components lazy-loaded to accelerate startup

__all__ = [
    'ArchiveBrowser',
    'CustomFileSelector',
    'FileStagingPool',
    'FileInfoPreviewer',
    'FolderContentList',
    'FontPreviewer',
    'PDFPreviewer',
    'PhotoViewer',
    'TextPreviewer',
    'UnifiedPreviewer',
    'VideoPlayer',
    'ThemeEditor'
]

_LAZY_IMPORTS = {
    'ArchiveBrowser': '.archive_browser',
    'CustomFileSelector': '.file_selector',
    'FileStagingPool': '.file_staging_pool',
    'FileInfoPreviewer': '.file_info_previewer',
    'FolderContentList': '.folder_content_list',
    'FontPreviewer': '.font_previewer',
    'PDFPreviewer': '.pdf_previewer',
    'PhotoViewer': '.photo_viewer',
    'TextPreviewer': '.text_previewer',
    'UnifiedPreviewer': '.unified_previewer',
    'VideoPlayer': '.video_player',
    'ThemeEditor': '.theme_editor',
}


def __getattr__(name):
    if name in _LAZY_IMPORTS:
        import importlib
        module = importlib.import_module(_LAZY_IMPORTS[name], __package__)
        component = getattr(module, name)
        globals()[name] = component
        return component
    raise AttributeError(f"module 'freeassetfilter.components' has no attribute {name!r}")
