from freeassetfilter.utils.markdown_renderer import MarkdownRenderer
md = """[![GitHub Release](https://img.shields.io/github/v/release/Dorufoc/FreeAssetFilter?style=flat-square\\&logo=github\\&color=blue)](https://github.com/Dorufoc/FreeAssetFilter/releases) [![Python Version](https://img.shields.io/badge/Python-3.9%2B-blue?style=flat-square\\&logo=python)](https://www.python.org/) [![PySide6](https://img.shields.io/badge/PySide6-6.4%2B-green?style=flat-square\\&logo=qt)](https://wiki.qt.io/Qt_for_Python) [![License](https://img.shields.io/badge/License-AGPL--3.0-orange?style=flat-square)](LICENSE) [![Platform](https://img.shields.io/badge/Platform-Windows-purple?style=flat-square\\&logo=windows)](https://www.microsoft.com/windows)"""

html = MarkdownRenderer().render(md)
print(html)
