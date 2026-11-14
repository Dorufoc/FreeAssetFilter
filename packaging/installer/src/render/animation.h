#pragma once
//
// animation.h - 帧时钟 / 缓动 / 可动画值（Frozen contract §16 可观测性）。
//
// 纯逻辑：本模块**不依赖 Windows / HWND**，可在离屏 harness 中独立驱动。HWND +
// `WM_TIMER(~16ms)` 的 tick 接线（advance → PresentFrame → Commit、闲置 KillTimer、
// 新动画重新武装）归 `installer_window.cpp` 所有（本 todo 唯一拥有该接线）。
//
// 缓动为**真实 cubic-bezier 解算**（Newton-Raphson + 二分回退），曲线常数见
// `easing` 命名空间；WinUI3 运动曲线的约定值在注释中逐条记录。
//
// §16 可观测性：`Animator` 每 tick 对**每个活动** `AnimValue` 采样一行日志
// （名称 + 时间戳 + 当前值），并在动画开始/结束各写一条边界行。sink 可注入
// （生产接 `DiagLog`；harness 接文件），模块内**不硬编码任何文件路径**。
//
#include <cstddef>
#include <functional>
#include <memory>
#include <string>
#include <vector>

namespace spk {

// 三次贝塞尔缓动曲线：P0=(0,0)、P3=(1,1)，由控制点 P1=(x1,y1)、P2=(x2,y2) 决定。
// 与 CSS `cubic-bezier(x1,y1,x2,y2)` / WinUI3 缓动同义：沿 x 轴求参数 t 使
// bezierX(t)=x，再返回 bezierY(t)。
struct CubicBezier {
    float x1 = 0.1f;  // P1.x
    float y1 = 0.9f;  // P1.y
    float x2 = 0.2f;  // P2.x
    float y2 = 1.0f;  // P2.y

    // x∈[0,1]（归一化进度）→ 缓动后 y∈[0,1]。x 越界时钳制到端点。
    // 控制点落在对角线上时退化为恒等线性（快速路径）。
    float Ease(float x) const;
};

// WinUI3 / Fluent 运动曲线（冻结常数，禁止另行发明）。
namespace easing {
// 入场（decelerate）：快速起步、缓慢收尾。计划冻结的 WinUI3 入场曲线。
constexpr CubicBezier Entrance{0.1f, 0.9f, 0.2f, 1.0f};
// 出场（accelerate）：缓慢起步、快速收尾。
constexpr CubicBezier Exit{0.7f, 0.0f, 1.0f, 0.5f};
// 标准（对称，进入与退出通用）。
constexpr CubicBezier Standard{0.8f, 0.0f, 0.2f, 1.0f};
// 线性：仅用于 harness 的对照断言（非 UI 使用）。
constexpr CubicBezier Linear{0.0f, 0.0f, 1.0f, 1.0f};
}  // namespace easing

// 一个可动画标量。推进**只发生在 UI 线程的 tick**，绝不阻塞安装线程。
class AnimValue {
public:
    AnimValue() = default;

    // 配置（重新）开始一次动画。durationMs<=0 表示直接终态（减少动画路径）：
    // 不会产生中间 tick，首个 tick 即落到终值。
    void Configure(std::string name, float from, float to, float durationMs, CubicBezier curve);

    // 重定向动画终值：活动时**只**更新 to_，保留 from_/startMs_/progress_/durationMs_，
    // 避免高频更新时反复重启导致轨迹推进被清零；非活动时从当前 value_ 起跑，
    // 沿用既有 durationMs_/curve_（减少动画的 0 时长同样沿用）。
    void Retarget(float to);

    // 用当前时间（毫秒，单调）推进。返回推进后是否仍活动。
    bool Advance(double nowMs);

    bool IsActive() const noexcept { return active_; }
    bool Started() const noexcept { return started_; }
    float Value() const noexcept { return value_; }
    float Progress() const noexcept { return progress_; }
    float DurationMs() const noexcept { return durationMs_; }
    float From() const noexcept { return from_; }
    float Target() const noexcept { return to_; }
    const std::string& Name() const noexcept { return name_; }

    // 直接落到终态（不产生中间 tick）。减少动画场景可选使用。
    void FinishImmediately();

private:
    std::string name_;
    float from_ = 0.0f;
    float to_ = 1.0f;
    float durationMs_ = 0.0f;
    CubicBezier curve_{};
    double startMs_ = 0.0;
    float value_ = 0.0f;
    float progress_ = 0.0f;
    bool started_ = false;
    bool active_ = false;
};

// 帧时钟：统一推进所有活动 `AnimValue`，并产出 §16 可观测日志。
class Animator {
public:
    // §16 日志 sink（一行一条）。未注入时所有采样为 no-op。
    using Sink = std::function<void(const std::string&)>;

    Animator() = default;

    // 注入 §16 日志 sink（生产 = DiagLog；harness = 写文件）。
    void SetSink(Sink sink) { sink_ = std::move(sink); }

    // 减少动画：为 true 时，**新**动画时长强制为 0 → 首个 tick 内 start==end。
    void SetReduceMotion(bool enabled) noexcept { reduceMotion_ = enabled; }
    bool ReduceMotion() const noexcept { return reduceMotion_; }

    // 新建（或按名称重用）一个动画并开始。返回稳定引用（`unique_ptr` 存储，
    // 后续 Animate/Tick 不会使既有引用失效）。reduce-motion 开启时时长被置 0。
    AnimValue& Animate(std::string name, float from, float to, float durationMs,
                       CubicBezier curve = easing::Entrance);

    // 推进一帧：对每个活动值采样一行（§16），并写开始/结束边界行。
    // 返回：本 tick 是否**推进了任何**动画（供 installer_window 决定是否 Present——
    // 终结帧（value 到终值的那一 tick）同样返回 true，确保终态被绘制）。
    bool Tick(double nowMs);

    // 调用后是否仍有活动动画（供闲置判定：无活动且无 dirty ⇒ KillTimer）。
    bool IsActive() const noexcept;
    std::size_t ActiveCount() const noexcept;

    // 停止并移除全部动画（不做完成日志）。
    void Clear();

private:
    void Emit(const std::string& line) const;

    Sink sink_;
    bool reduceMotion_ = false;
    std::vector<std::unique_ptr<AnimValue>> values_;
};

// 单调高精度毫秒时钟（std::chrono::steady_clock，自首次调用起算）。
// 全项目统一使用此时间源（含 installer_window 与 harness）。
double SteadyNowMs();

}  // namespace spk
