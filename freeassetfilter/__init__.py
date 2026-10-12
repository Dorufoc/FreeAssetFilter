# FreeAssetFilter 主包

from ._import_compat import install as _install_import_compat

# 统一 theme/components 短路径与 freeassetfilter.ui.* 规范路径的导入别名，
# 避免同一包被两条路径各执行一次（双单例）。详见 _import_compat 模块。
_install_import_compat()
del _install_import_compat

__version__ = "1.0.0"
__author__ = "Dorufoc | renmoren"
__email__ = "dorufoc@outlook.com | renmoren@foxmail.com"
