# Sopeek 主包

from ._import_compat import install as _install_import_compat

# 统一 theme/components 短路径与 sopeek.ui.* 规范路径的导入别名，
# 避免同一包被两条路径各执行一次（双单例）。详见 _import_compat 模块。
_install_import_compat()
del _install_import_compat

def _read_local_version() -> str:
    """从 ``SPKVERSION`` 读取版本号（运行时唯一来源）。

    延迟导入并吞掉一切异常：包初始化阶段任何失败都不应阻断启动，
    缺失时回退 ``0.0.0``。
    """
    try:
        from sopeek.utils.version_info import get_local_version

        return get_local_version()
    except Exception:  # noqa: BLE001 - 版本号缺失绝不影响程序可用性
        return "0.0.0"


__version__ = _read_local_version()
del _read_local_version
__author__ = "Dorufoc | renmoren"
__email__ = "dorufoc@outlook.com | renmoren@foxmail.com"
