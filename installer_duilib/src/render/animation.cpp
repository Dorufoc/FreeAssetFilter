//
// animation.cpp - 帧时钟 / 缓动 / 可动画值实现（Frozen contract §16 可观测性）。
//
// 纯逻辑，无 Windows 依赖。缓动为真实 cubic-bezier 解算；可观测性日志由本模块
// 经注入 sink 产出（生产 = installer_window 的 DiagLog，harness = 文件）。
//
#include "render/animation.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>

namespace faf {

namespace {

// 三次贝塞尔单分量：B(t) = 3(1-t)^2 t p1 + 3(1-t) t^2 p2 + t^3（端点 0 与 1）。
float BezierComponent(float t, float p1, float p2) {
    const float u = 1.0f - t;
    return 3.0f * u * u * t * p1 + 3.0f * u * t * t * p2 + t * t * t;
}

// 该分量的导数 dB/dt：3(1-t)^2 p1 + 6(1-t) t (p2-p1) + 3 t^2 (1-p2)。
float BezierSlope(float t, float p1, float p2) {
    const float u = 1.0f - t;
    return 3.0f * u * u * p1 + 6.0f * u * t * (p2 - p1) + 3.0f * t * t * (1.0f - p2);
}

// §16 采样/边界行格式化：kind name=<n> t=<ms> v=<value>。
std::string FormatAnimLine(const char* kind, const std::string& name, double nowMs, float value) {
    char buf[192];
    std::snprintf(buf, sizeof(buf), "%s name=%s t=%.2f v=%.5f", kind, name.c_str(), nowMs,
                  static_cast<double>(value));
    return std::string(buf);
}

}  // namespace

float CubicBezier::Ease(float x) const {
    if (x <= 0.0f) return 0.0f;
    if (x >= 1.0f) return 1.0f;
    // 控制点落在对角线上（如 Linear {0,0,1,1}）⇒ 恒等线性。
    if (x1 == y1 && x2 == y2) return x;

    // Newton-Raphson：以 t=x 起步（x→t 映射对缓动曲线是好的初值），通常 2-3 次收敛。
    float t = x;
    for (int i = 0; i < 4; ++i) {
        const float err = BezierComponent(t, x1, x2) - x;
        if (err == 0.0f) break;
        const float slope = BezierSlope(t, x1, x2);
        if (slope == 0.0f) break;
        t -= err / slope;
    }
    t = std::min(std::max(t, 0.0f), 1.0f);

    // 二分回退：Newton 未收敛（斜率平坦处）时保证精度，x(t) 关于 t 单调。
    float lo = 0.0f;
    float hi = 1.0f;
    for (int i = 0; i < 24; ++i) {
        const float fx = BezierComponent(t, x1, x2) - x;
        if (std::fabs(fx) < 1e-6f) break;
        if (fx > 0.0f)
            hi = t;
        else
            lo = t;
        t = 0.5f * (lo + hi);
    }
    return BezierComponent(t, y1, y2);
}

void AnimValue::Configure(std::string name, float from, float to, float durationMs,
                          CubicBezier curve) {
    name_ = std::move(name);
    from_ = from;
    to_ = to;
    durationMs_ = durationMs < 0.0f ? 0.0f : durationMs;
    curve_ = curve;
    startMs_ = 0.0;
    value_ = from;
    progress_ = 0.0f;
    started_ = false;
    active_ = true;  // 待首个 tick 落 start（减少动画时同 tick 直接终态）
}

void AnimValue::Retarget(float to) {
    if (!active_) {
        // 无活动动画：从当前显示值重新起跑，保留已配置的时长与曲线。
        from_ = value_;
        to_ = to;
        startMs_ = 0.0;
        progress_ = 0.0f;
        started_ = false;
        active_ = true;
        return;
    }
    // 活动动画：仅更新终值，让既有轨迹继续推进（不重置起点/时钟/进度）。
    to_ = to;
}

bool AnimValue::Advance(double nowMs) {
    if (!active_) return false;
    if (!started_) {
        startMs_ = nowMs;
        started_ = true;
    }
    if (durationMs_ <= 0.0f) {
        // 减少动画 / 零时长：直接终态，无中间值。
        value_ = to_;
        progress_ = 1.0f;
        active_ = false;
        return false;
    }
    const double elapsed = nowMs - startMs_;
    float progress = static_cast<float>(elapsed / static_cast<double>(durationMs_));
    if (progress < 0.0f) progress = 0.0f;
    if (progress >= 1.0f) {
        value_ = to_;
        progress_ = 1.0f;
        active_ = false;
        return false;
    }
    progress_ = progress;
    value_ = from_ + (to_ - from_) * curve_.Ease(progress);
    return true;
}

void AnimValue::FinishImmediately() {
    value_ = to_;
    progress_ = 1.0f;
    active_ = false;
}

AnimValue& Animator::Animate(std::string name, float from, float to, float durationMs,
                             CubicBezier curve) {
    // 减少动画：时长置 0 ⇒ 首个 tick 内 start==end（不产生中间 tick）。
    const float effectiveDuration = reduceMotion_ ? 0.0f : std::max(0.0f, durationMs);
    for (auto& vp : values_) {
        if (vp->Name() == name) {
            vp->Configure(std::move(name), from, to, effectiveDuration, curve);
            return *vp;
        }
    }
    values_.push_back(std::make_unique<AnimValue>());
    values_.back()->Configure(std::move(name), from, to, effectiveDuration, curve);
    return *values_.back();
}

bool Animator::Tick(double nowMs) {
    bool worked = false;
    for (auto& vp : values_) {
        AnimValue& v = *vp;
        if (!v.IsActive()) continue;
        const bool firstTick = !v.Started();
        v.Advance(nowMs);
        if (firstTick) Emit(FormatAnimLine("anim-begin", v.Name(), nowMs, v.Value()));
        // §16：每 tick 采样活动值的当前值（端点行不足以证明单调/非线性）。
        Emit(FormatAnimLine("anim-sample", v.Name(), nowMs, v.Value()));
        if (!v.IsActive()) Emit(FormatAnimLine("anim-end", v.Name(), nowMs, v.Value()));
        worked = true;
    }
    return worked;
}

bool Animator::IsActive() const noexcept {
    for (const auto& vp : values_) {
        if (vp->IsActive()) return true;
    }
    return false;
}

std::size_t Animator::ActiveCount() const noexcept {
    std::size_t count = 0;
    for (const auto& vp : values_) {
        if (vp->IsActive()) ++count;
    }
    return count;
}

void Animator::Clear() { values_.clear(); }

void Animator::Emit(const std::string& line) const {
    if (sink_) sink_(line);
}

double SteadyNowMs() {
    using Clock = std::chrono::steady_clock;
    static const Clock::time_point origin = Clock::now();
    return std::chrono::duration<double, std::milli>(Clock::now() - origin).count();
}

}  // namespace faf
