# Todo 19（§17）：测试构建开关（SPK_TESTMODE）。
#
# 默认 OFF：生产构建（build.ps1 直接 configure、不传任何测试参数）分毫不变 ——
# SPK_TESTMODE 未定义时：main.cpp 仅解析 /auto 而不驱动；installer_window 中的
# 驱动成员/定时器/推进逻辑全部被预处理器剔除（零残留）。
#
# 仅测试 GUI 构建（tools/build_test_gui.ps1）显式传入 -DSPK_TESTMODE=ON：
# 定义宏后 /auto、/auto:opts=<bits>、/auto:page=N 才真正驱动无人值守流程。
# 该开关绝不允许进入生产构建/最终 Setup.exe。

option(SPK_TESTMODE "Build the installer GUI with the /auto unattended test drive enabled" OFF)

if(SPK_TESTMODE)
    target_compile_definitions(SopeekInstaller PRIVATE SPK_TESTMODE)
endif()
