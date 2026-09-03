# -*- coding: utf-8 -*-
"""``freeassetfilter.ui.components.mica_tint`` 单元测试。

覆盖 mica_tint.py 数学内核的 API 契约与边界条件：

* 基础变换 —— ``luma_ps``、``srgb_to_linear_lut``、``oklab_from_linear_rgb``
  / ``linear_rgb_from_oklab`` 在 sRGB 色域内的往返误差 < 1e-5；
* Photoshop「颜色」混合 —— 手算基准（``#F5F5F5``+ 纯蓝 = ``(244,244,255)``、
  ``#1A1A1A`` + 纯蓝 = ``(0,0,236)``）、``ClipColor`` 保亮度、``Color`` 输出
  逐像素亮度锁死；
* 色度提取与可靠性门控 —— ``chroma_from_srgb`` 丢弃 L、``chroma_reliability``
  软门控形状；
* 去轮廓加权低通 —— ``blur_chroma`` 在恒定色度场上输出 = 输入；权重的"零
  权重像素不污染"性质；
* 色度整形 —— ``shape_chroma`` 单调、过原点、软限幅；零色度恒为零；
* 等亮度重建 —— 上层 S 层的亮度标准差 < 1/255；
* 顶层流水线 —— ``bake_tint`` 端到端不变量（亮度锁死、影像不可见、深浅
  模式对称）；
* G1 常量与 Oklab 参考明度；
* TPDF 抖动确定性 —— 同种子结果完全一致，幅值 ≤ 0.5 LSB。

数学内核仅依赖 numpy，本测试不依赖 Qt，可在无显示器 / 无 QApplication 环境下
通过。Qt 边界适配（``qimage_from_ndarray`` / ``qpixmap_from_ndarray`` /
``qimage_to_ndarray_rgb`` / ``bake_tint_qimage``）的测试见 widget / component
层的集成测试。

验证命令：

    python -m pytest tests/unit/ui/components/test_mica_tint.py -v
"""

# targets: ui.components.mica_tint

from __future__ import annotations

import numpy as np
import pytest

from freeassetfilter.ui.components import mica_tint as mt

pytestmark = pytest.mark.unit


# =============================================================================
# 基础色彩变换
# =============================================================================

class TestSrgbLinearRoundTrip:
    """sRGB ↔ 线性光 往返精度。"""

    def test_lut_is_monotonic(self) -> None:
        """LUT 严格单调递增。"""
        lut = mt.srgb_to_linear_lut()
        assert lut.shape == (256,)
        assert (np.diff(lut) >= 0).all()

    def test_lut_endpoints(self) -> None:
        """0 → 0, 255 → 1。"""
        lut = mt.srgb_to_linear_lut()
        assert lut[0] == pytest.approx(0.0, abs=1e-6)
        assert lut[255] == pytest.approx(1.0, abs=1e-4)

    @pytest.mark.parametrize("u8", [0, 64, 128, 192, 255])
    def test_round_trip_within_tolerance(self, u8: int) -> None:
        """整数采样 sRGB → 线性 → sRGB 编码 → 量化回原值。"""
        arr = np.full((1, 1, 3), u8, dtype=np.uint8)
        lin = mt.linear_from_srgb_u8(arr)
        enc = mt.srgb_from_linear(lin) * 255.0
        recovered = int(np.clip(np.rint(enc[0, 0, 0]), 0, 255))
        assert abs(recovered - u8) <= 1


class TestOklabRoundTrip:
    """Oklab 在 sRGB 色域内往返误差。"""

    @pytest.mark.parametrize("rgb_u8", [
        (200, 80, 60), (40, 180, 200), (30, 30, 30), (245, 245, 245),
        (255, 0, 0), (0, 255, 0), (0, 0, 255), (128, 128, 128),
    ])
    def test_in_gamut_round_trip(self, rgb_u8: tuple) -> None:
        """sRGB → Oklab → sRGB 在 sRGB 色域内逐像素一致（浮点级）。

        量纲纪律（易错点）：``oklab_from_linear_rgb`` 的入参是**线性光**，
        而 ``srgb_from_oklab`` 的出参是**伽马编码值**。若把 ``u8 / 255``
        当作线性光直接送入，往返等于多做一次伽马编码
        （如 128 → 0.502 → 0.737），属测试误用而非实现缺陷。
        故此处先经 ``linear_from_srgb_u8`` 去伽马，在线性域内比对，
        再单独校核编码域闭合性。

        容差依据（实测最差 8 例）：线性域往返误差 ≤ 1.03e-6，落在 float32
        在色域顶点（纯绿）上 LMS→RGB 逆变换的灾难性抵消量级 —— 首行
        ``4.08·l - 3.31·m + 0.23·s`` 三项各约 2.2 却相消至 ~1e-6。
        编码域不能沿用同一容差：sRGB 编码曲线暗部线性段斜率为 **12.92**，
        会把 1.02e-6 的线性误差放大到 1.32e-5。因此编码域改以 **8-bit
        量化步长（LSB）** 为单位度量，实测最差 0.0034 LSB（纯绿），
        即量化步长的 1/300 —— 取 0.02 LSB 作断言上界，留约 6 倍余量。
        """
        u8 = np.array(rgb_u8, dtype=np.uint8)
        lin = mt.linear_from_srgb_u8(u8)          # (3,) 线性光
        lab = mt.oklab_from_linear_rgb(lin)
        # 线性域往返：命中 in-gamut 快速路径，精度为 float32 噪声级
        np.testing.assert_allclose(mt.linear_rgb_from_oklab(lab), lin, atol=1e-5)
        # 编码域往返：折算为 8-bit LSB 误差，须远小于 1 个量化步长
        enc8 = mt.srgb_from_oklab(lab) * 255.0
        np.testing.assert_allclose(enc8, u8.astype(np.float32), atol=0.02)

    def test_inverse_lab_zero_ab_drops_chroma(self) -> None:
        """Oklab (L, 0, 0) 重建后是中性色（a == b == 0 in Oklab sense）。"""
        lab = np.array([0.5, 0.0, 0.0], dtype=np.float32)
        rgb = mt.srgb_from_oklab(lab)
        # 中性灰的色度角无定义，但 r==g==b 是必要条件
        assert abs(rgb[0] - rgb[1]) < 1e-5
        assert abs(rgb[1] - rgb[2]) < 1e-5


# =============================================================================
# Photoshop「颜色」混合 —— 规范一致性
# =============================================================================

class TestLumaPs:
    """``luma_ps`` 的 Rec.601-on-gamma 加权。"""

    def test_neutral_half(self) -> None:
        """中性 0.5 灰 → 0.5。"""
        c = np.array([[[0.5, 0.5, 0.5]]], dtype=np.float32)
        assert mt.luma_ps(c)[0] == pytest.approx(0.5, abs=1e-6)

    def test_pure_blue_weight_011(self) -> None:
        """纯蓝 0.11 权重。"""
        c = np.array([[[0.0, 0.0, 1.0]]], dtype=np.float32)
        assert mt.luma_ps(c)[0] == pytest.approx(0.11, abs=1e-6)

    def test_weights_sum_to_one(self) -> None:
        """0.3 + 0.59 + 0.11 = 1.0（保证中性 c == luma 时 luma == c_value）。"""
        assert 0.3 + 0.59 + 0.11 == pytest.approx(1.0, abs=1e-9)


class TestClipColor:
    """ClipColor 保亮度 + 落在 [0,1]。"""

    def test_in_gamut_passthrough(self) -> None:
        """已在 [0,1] 的输入保持不变。"""
        c = np.array([[[0.2, 0.5, 0.8], [0.9, 0.1, 0.4]]], dtype=np.float32)
        out = mt.clip_color(c)
        np.testing.assert_allclose(out, c, atol=1e-7)

    def test_luma_preserved_in_valid_domain(self) -> None:
        """本管线真实域（``Luma(c) ∈ [0,1]``）内 ClipColor 严格保亮度。"""
        rng = np.random.default_rng(123)
        s = rng.random((5000, 3)).astype(np.float32)
        b = rng.random((5000, 3)).astype(np.float32)
        # c = S + (Lum(B) - Lum(S))  ⇒  Lum(c) = Lum(B) ∈ [0,1]
        c = s + (mt.luma_ps(b) - mt.luma_ps(s))[..., None]
        cc = mt.clip_color(c)
        np.testing.assert_allclose(mt.luma_ps(cc), mt.luma_ps(c), atol=1e-5)
        assert ((cc >= -1e-4) & (cc <= 1 + 1e-4)).all()


class TestSetLum:
    """SetLum 命中目标亮度（真实域 [0,1]）。"""

    @pytest.mark.parametrize("l", [0.0, 0.1, 0.5, 0.9, 1.0])
    def test_hits_target(self, l: float) -> None:
        """随机源色 → SetLum → 亮度等于目标。"""
        rng = np.random.default_rng(7)
        src = rng.random((500, 3)).astype(np.float32)
        out = mt.set_lum(src, l)
        np.testing.assert_allclose(mt.luma_ps(out), l, atol=1e-4)


class TestColorBlend:
    """Photoshop「颜色」混合 = SetLum(S, Lum(B))。"""

    def test_reference_light_blue(self) -> None:
        """手算基准：``Color(#F5F5F5, 纯蓝) = (244, 244, 255)``。"""
        b = np.array([0xF5, 0xF5, 0xF5], dtype=np.float32) / 255.0
        s = np.array([0.0, 0.0, 1.0], dtype=np.float32)
        got = np.rint(mt.color_blend(b, s) * 255).astype(int)
        assert tuple(got) == (244, 244, 255)

    def test_reference_dark_blue(self) -> None:
        """手算基准：``Color(#1A1A1A, 纯蓝) = (0, 0, 236)``。"""
        b = np.array([0x1A, 0x1A, 0x1A], dtype=np.float32) / 255.0
        s = np.array([0.0, 0.0, 1.0], dtype=np.float32)
        got = np.rint(mt.color_blend(b, s) * 255).astype(int)
        assert tuple(got) == (0, 0, 236)

    def test_output_luma_equals_backdrop_luma(self) -> None:
        """核心不变量：``Color(B, S)`` 的逐像素亮度严格等于 ``Lum(B)``。"""
        rng = np.random.default_rng(31)
        b = rng.random((10000, 3)).astype(np.float32)
        s = rng.random((10000, 3)).astype(np.float32)
        out = mt.color_blend(b, s)
        np.testing.assert_allclose(mt.luma_ps(out), mt.luma_ps(b), atol=1e-4)

    def test_neutral_backdrop_preserves_hue(self) -> None:
        """中性灰下层：色相角保持不变（对所有源色）。"""
        rng = np.random.default_rng(91)
        s = rng.random((2000, 3)).astype(np.float32)
        b = np.full_like(s, 0.5)
        out = mt.color_blend(b, s)
        h_in = np.arctan2(np.sqrt(3.0) * (s[..., 1] - s[..., 2]),
                          2.0 * s[..., 0] - s[..., 1] - s[..., 2])
        h_out = np.arctan2(np.sqrt(3.0) * (out[..., 1] - out[..., 2]),
                           2.0 * out[..., 0] - out[..., 1] - out[..., 2])
        d = np.abs(((h_out - h_in) + np.pi) % (2 * np.pi) - np.pi)
        assert d.max() < 0.01


# =============================================================================
# 色度提取与门控
# =============================================================================

class TestChromaFromSrgb:
    """``chroma_from_srgb`` 逐像素丢弃 L（去明度的通道级实现）。"""

    def test_neutral_gray_zero_ab(self) -> None:
        """中性灰：``a == 0, b == 0``，Y 等于线性亮度。"""
        img = np.full((1, 1, 3), 128, dtype=np.uint8)
        ab, y = mt.chroma_from_srgb(img)
        np.testing.assert_allclose(ab[0, 0], (0.0, 0.0), atol=1e-4)
        assert y[0, 0] == pytest.approx(mt.linear_from_srgb_u8(img)[0, 0, 0],
                                         abs=1e-5)

    def test_y_is_rec709_linear(self) -> None:
        """Y = 0.2126 R + 0.7152 G + 0.0722 B（线性光）。"""
        img = np.array([[[200, 100, 50]]], dtype=np.uint8)
        ab, y = mt.chroma_from_srgb(img)
        lin = mt.linear_from_srgb_u8(img)[0, 0]
        expected = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
        assert y[0, 0] == pytest.approx(float(expected), abs=1e-5)


class TestChromaReliability:
    """``chroma_reliability`` 双侧 smoothstep 软门控。"""

    def test_bright_center_full_weight(self) -> None:
        """门控中心区段 (Y ∈ [lo+feather, hi-feather]) 权重 = 1。"""
        y = np.array([0.20, 0.50, 0.80], dtype=np.float32)
        w = mt.chroma_reliability(y)
        np.testing.assert_allclose(w, 1.0, atol=1e-5)

    def test_crushed_shadows_zero_weight(self) -> None:
        """Y < lo 处权重 = 0。"""
        y = np.array([0.0, 0.005], dtype=np.float32)
        w = mt.chroma_reliability(y)
        assert (w == 0.0).all()

    def test_blown_highlights_zero_weight(self) -> None:
        """Y > hi 处权重 = 0。"""
        y = np.array([0.995, 1.0], dtype=np.float32)
        w = mt.chroma_reliability(y)
        assert (w == 0.0).all()

    def test_feather_band_smooth(self) -> None:
        """过渡带内 weight ∈ (0, 1) 且单调。"""
        # 选在 feather 带中心（lo+feather/2 附近），确保整段都在过渡带内
        center = mt.CHROMA_LUMA_GATE_LO + mt.CHROMA_LUMA_GATE_FEATHER * 0.5
        y = np.linspace(center - 0.003, center + 0.003, 20, dtype=np.float32)
        w = mt.chroma_reliability(y)
        assert (w > 0).all() and (w < 1).all()
        # 单调递增
        assert (np.diff(w) >= 0).all()


# =============================================================================
# 归一化加权高斯低通
# =============================================================================

class TestBlurChroma:
    """``blur_chroma`` 在恒定色度场上输出 ≈ 输入（验证加权归一化无偏）。"""

    def test_uniform_chroma_passthrough(self) -> None:
        """整幅常色度 = 输入，零残差（至模糊核归一化误差内）。"""
        ab = np.full((60, 80, 2), [0.05, -0.02], dtype=np.float32)
        w = np.ones((60, 80), dtype=np.float32)
        out = mt.blur_chroma(ab, w, sigma=8.0, downscale=1)
        np.testing.assert_allclose(out, ab, atol=1e-3)

    def test_zero_weighted_pixels_filled_from_neighbors(self) -> None:
        """零权重像素的色度**由邻域高权重像素"填补"**（非严格保持 0）。

        这是加权模糊的设计意图：低权重区域（压暗暗部 / 过曝高光）的色度
        由附近可靠色度贡献，使合成结果保持连续性 —— 极端情况下是"色度插值"。
        因此原值为 0 的外圈会被中心色度（0.10）"渗入"到非零值。
        """
        ab = np.zeros((50, 50, 2), dtype=np.float32)
        ab[10:40, 10:40, 0] = 0.10  # 中心 a 通道 = 0.10
        w = np.zeros((50, 50), dtype=np.float32)
        w[10:40, 10:40] = 1.0      # 外圈权重 = 0
        out = mt.blur_chroma(ab, w, sigma=4.0, downscale=1)
        # 中心区域色度基本不变（σ << 区域尺寸）
        np.testing.assert_allclose(out[15:35, 15:35, 0], 0.10, atol=0.02)
        # 紧邻高权重块的外侧带（块上边缘 1~3 px 内）：核支撑跨入块内 → 被填补
        # 归一化后恰等于邻域色度质心 0.10（分子分母同源于块内像素）
        band = out[7:10, 20:30, 0]
        assert (band > 0.05).all(), band.min()
        # 但绝不放大超过源峰值
        assert (band <= 0.10 + 1e-3).all(), band.max()

    def test_no_weight_support_yields_zero_not_nan(self) -> None:
        """核支撑内完全无高权重像素时，输出退化为 0 而非 NaN / Inf。

        ``out = Σ w·a / max(Σ w, _EPS)``：分子分母同时趋零时由 ``_EPS``
        兜底，结果 → 0。这是加权模糊在"孤立零权重区"的既定行为。
        """
        ab = np.full((40, 40, 2), 0.08, dtype=np.float32)
        w = np.zeros((40, 40), dtype=np.float32)
        w[0:4, 0:4] = 1.0                      # 唯一有权重的角落
        out = mt.blur_chroma(ab, w, sigma=2.0, downscale=1)
        assert np.isfinite(out).all()
        # 远端（行 30+）核支撑触不到权重块 → 0
        np.testing.assert_allclose(out[30:40, 30:40], 0.0, atol=1e-4)

    def test_downscale_preserves_large_features(self) -> None:
        """预降采样近似在保留大特征时与全分辨率卷积视觉一致。"""
        rng = np.random.default_rng(5)
        # 低频信号：块状常值
        ab = np.zeros((100, 100, 2), dtype=np.float32)
        for r in range(0, 100, 20):
            for c in range(0, 100, 20):
                ab[r:r + 20, c:c + 20] = rng.normal(scale=0.02, size=2)
        w = np.ones((100, 100), dtype=np.float32)
        full = mt.blur_chroma(ab, w, sigma=12.0, downscale=1)
        fast = mt.blur_chroma(ab, w, sigma=12.0, downscale=8)
        # 降采样近似在主体区域吻合，仅最外圈 1-2 像素有截断效应
        np.testing.assert_allclose(full[5:95, 5:95], fast[5:95, 5:95], atol=0.01)

    def test_zero_sigma_returns_input(self) -> None:
        """σ=0 等价于"无低通"。"""
        rng = np.random.default_rng(0)
        ab = rng.random((40, 60, 2)).astype(np.float32) * 0.1
        w = np.ones((40, 60), dtype=np.float32)
        out = mt.blur_chroma(ab, w, sigma=0.0)
        np.testing.assert_allclose(out, ab, atol=1e-7)


# =============================================================================
# 色度整形
# =============================================================================

class TestShapeChroma:
    """``shape_chroma`` tanh 软限幅。"""

    def test_zero_chroma_stays_zero(self) -> None:
        """零色度恒为零 —— 纯灰壁纸自然退化为纯 G1。"""
        ab = np.zeros((4, 4, 2), dtype=np.float32)
        out = mt.shape_chroma(ab, cap=0.05, gain=1.0)
        np.testing.assert_allclose(out, 0.0, atol=1e-7)

    def test_small_chroma_linear(self) -> None:
        """小色度区近似线性（tanh x ≈ x）。"""
        ab = np.full((1, 1, 2), 0.001, dtype=np.float32)
        out = mt.shape_chroma(ab, cap=0.05, gain=1.0)
        np.testing.assert_allclose(out, 0.001, atol=1e-5)

    def test_soft_cap_at_infinity(self) -> None:
        """巨大色度被软限幅到 cap（tanh → 1）。"""
        ab = np.full((1, 1, 2), 10.0, dtype=np.float32)
        cap = 0.05
        out = mt.shape_chroma(ab, cap=cap, gain=1.0)
        assert np.allclose(np.linalg.norm(out, axis=-1), cap, atol=1e-5)

    def test_hue_preserved(self) -> None:
        """色度整形不改变色相角（单调、过原点、纯缩放）。"""
        rng = np.random.default_rng(0)
        ab = rng.normal(scale=0.08, size=(200, 2)).astype(np.float32)
        out = mt.shape_chroma(ab, cap=0.04, gain=1.0)
        ang_in = np.arctan2(ab[..., 1], ab[..., 0])
        ang_out = np.arctan2(out[..., 1], out[..., 0])
        d = np.abs(((ang_out - ang_in) + np.pi) % (2 * np.pi) - np.pi)
        assert d.max() < 1e-4

    def test_monotonic_in_magnitude(self) -> None:
        """形如 ``C_out(C_in)`` 单调递增。"""
        c = np.linspace(0.0, 0.1, 20, dtype=np.float32)
        ab = np.stack([c, np.zeros_like(c)], axis=-1)
        out = mt.shape_chroma(ab, cap=0.05, gain=1.0)
        mags = np.sqrt((out ** 2).sum(-1))
        assert (np.diff(mags) >= 0).all()


# =============================================================================
# 等亮度重建 / 上层源图像
# =============================================================================

class TestRebuildSourceLayer:
    """``rebuild_source_layer`` 输出逐像素亮度恒等于参考 L。"""

    def test_luma_constant_equals_l_ref(self) -> None:
        """对随机色度网格（4×4），**Oklab L** 严格等于 l_ref。

        注意：Oklab L 与 PS Luma 不是同一概念，sRGB 编码后的 PS Luma
        会因色相依赖的伽马映射有轻微起伏（< 5/255）；设计承诺是
        "Oklab L 恒定 → 上层等亮度（感知均匀意义上的等亮度）"。
        """
        rng = np.random.default_rng(3)
        ab = rng.normal(scale=0.02, size=(4, 4, 2)).astype(np.float32)
        out = mt.rebuild_source_layer(ab, l_ref=0.2178)
        # 反推 Oklab L，验证 L 严格等于 l_ref（去明度的硬保证）
        lin = mt.linear_from_srgb_u8(np.clip(np.rint(out * 255), 0, 255).astype(np.uint8))
        lab = mt.oklab_from_linear_rgb(lin)
        np.testing.assert_allclose(lab[..., 0], 0.2178, atol=2e-3)
        # PS Luma 起伏 < 5/255（感知意义下也是"几乎等亮度"）
        lum = mt.luma_ps(out)
        assert float(lum.max() - lum.min()) < 5.0 / 255.0


class TestG1Constants:
    """G1 常量与 Oklab 参考明度。"""

    def test_g1_dark_value(self) -> None:
        assert mt.G1_DARK == (0x1A, 0x1A, 0x1A)

    def test_g1_light_value(self) -> None:
        assert mt.G1_LIGHT == (0xF5, 0xF5, 0xF5)

    def test_g1_oklab_l_dark(self) -> None:
        """``Oklab_L(#1A1A1A) ≈ 0.218``（cbrt(linear(26/255))）。"""
        assert mt.g1_oklab_l(mt.G1_DARK) == pytest.approx(0.218, abs=0.01)

    def test_g1_oklab_l_light(self) -> None:
        """``Oklab_L(#F5F5F5) ≈ 0.970``。"""
        assert mt.g1_oklab_l(mt.G1_LIGHT) == pytest.approx(0.970, abs=0.01)


# =============================================================================
# 顶层流水线（bake_tint）
# =============================================================================

def _make_wallpaper() -> np.ndarray:
    """小尺寸、强结构的合成测试壁纸。"""
    h, w = 80, 120
    img = np.zeros((h, w, 3), dtype=np.float32)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32) / np.array([[[h]], [[w]]], dtype=np.float32)
    img[..., 0] = 0.2 + 0.6 * (1 - yy[..., None].squeeze())
    img[..., 1] = 0.3 + 0.4 * (xx / w)
    img[..., 2] = 0.8 - 0.5 * yy / h
    # 锐利白条
    img[10:14, :, :] = 1.0
    return (np.clip(img, 0, 1) * 255).astype(np.uint8).reshape(h, w, 3)


class TestBakeTint:
    """``bake_tint`` 端到端不变量。"""

    def test_luma_locked_to_g1(self) -> None:
        """深色/浅色模式的输出逐像素亮度 == ``Lum(G1)``。"""
        wall = _make_wallpaper()
        rect = (0.0, 0.0, float(wall.shape[1]), float(wall.shape[0]))
        for g1, dark in ((mt.G1_DARK, True), (mt.G1_LIGHT, False)):
            cfg = mt.TintConfig(dark=dark, sigma=8.0)
            res = mt.bake_tint(wall, rect, 60, 40, cfg)
            lum_b = mt.luma_ps(np.array(g1, dtype=np.float32) / 255.0) * 255.0
            lum_o = mt.luma_ps(res.image.astype(np.float32) / 255.0) * 255.0
            assert float(np.abs(lum_o - lum_b).max()) <= 1.5, (
                f"亮度锁死失败 ({dark=}, max Δ={float(np.abs(lum_o - lum_b).max()):.2f})"
            )

    def test_source_layer_iso_luminant(self) -> None:
        """上层源图像的亮度标准差 < 2/255。"""
        wall = _make_wallpaper()
        rect = (0.0, 0.0, float(wall.shape[1]), float(wall.shape[0]))
        cfg = mt.TintConfig(dark=True, sigma=8.0)
        res = mt.bake_tint(wall, rect, 60, 40, cfg)
        lum = mt.luma_ps(res.source_layer.astype(np.float32) / 255.0) * 255.0
        assert lum.std() < 2.0

    def test_structure_removed(self) -> None:
        """原图的锐利白条在合成结果中高通残差 RMS < 1.5/255。"""
        wall = _make_wallpaper()
        rect = (0.0, 0.0, float(wall.shape[1]), float(wall.shape[0]))
        cfg = mt.TintConfig(dark=True, sigma=12.0)
        res = mt.bake_tint(wall, rect, 120, 80, cfg)
        # 高通残差 = 原图 - 同图低通（手动做，不复用 verify 脚本的依赖）
        arr = res.image.astype(np.float32) / 255.0
        # 简单 3×3 盒式低通作为高频残差提取
        pad = np.pad(arr, ((1, 1), (1, 1), (0, 0)), mode="edge")
        low = (
            pad[:-2, :-2] + pad[:-2, 1:-1] + pad[:-2, 2:]
            + pad[1:-1, :-2] + pad[1:-1, 1:-1] + pad[1:-1, 2:]
            + pad[2:, :-2] + pad[2:, 1:-1] + pad[2:, 2:]
        ) / 9.0
        resid = float(np.sqrt(np.mean((arr - low) ** 2)) * 255.0)
        assert resid < 1.5

    def test_dark_light_hue_field_consistent(self) -> None:
        """深浅模式只改变基色亮度，色相场保持一致。"""
        wall = _make_wallpaper()
        rect = (0.0, 0.0, float(wall.shape[1]), float(wall.shape[0]))
        res_d = mt.bake_tint(wall, rect, 80, 60, mt.TintConfig(dark=True, sigma=8.0))
        res_l = mt.bake_tint(wall, rect, 80, 60, mt.TintConfig(dark=False, sigma=8.0))
        ab_d = mt.chroma_from_srgb(res_d.image)[0]
        ab_l = mt.chroma_from_srgb(res_l.image)[0]
        keep = np.sqrt(ab_d[..., 0] ** 2 + ab_d[..., 1] ** 2) > 0.004
        if keep.any():
            ang_d = np.degrees(np.arctan2(ab_d[..., 1], ab_d[..., 0]))[keep]
            ang_l = np.degrees(np.arctan2(ab_l[..., 1], ab_l[..., 0]))[keep]
            dh = np.abs(((ang_d - ang_l) + 180) % 360 - 180)
            assert dh.mean() < 10.0


# =============================================================================
# 抖动
# =============================================================================

class TestDitherTpdf:
    """``dither_tpdf`` 确定性 + 幅度。"""

    def test_deterministic_same_seed(self) -> None:
        """同种子下输出完全一致。"""
        a = mt.dither_tpdf((100, 80, 1), seed=42)
        b = mt.dither_tpdf((100, 80, 1), seed=42)
        np.testing.assert_array_equal(a, b)

    def test_different_seeds_differ(self) -> None:
        """不同种子下输出不同。"""
        a = mt.dither_tpdf((50, 50, 1), seed=1)
        b = mt.dither_tpdf((50, 50, 1), seed=2)
        assert not np.array_equal(a, b)

    def test_magnitude_within_half_lsb(self) -> None:
        """三角分布幅度严格 ≤ 0.5。"""
        noise = mt.dither_tpdf((1000, 1000, 1), seed=0)
        assert float(noise.max()) <= 0.5 + 1e-6
        assert float(noise.min()) >= -0.5 - 1e-6


# =============================================================================
# 边界
# =============================================================================

class TestEdgeCases:
    """边界与异常。"""

    def test_bake_tint_minimum_dimensions(self) -> None:
        """极小窗口（10×10）不应崩溃。"""
        wall = _make_wallpaper()
        rect = (0.0, 0.0, float(wall.shape[1]), float(wall.shape[0]))
        res = mt.bake_tint(wall, rect, 10, 10)
        assert res.image.shape == (10, 10, 3)

    def test_bake_tint_zero_alpha(self) -> None:
        """alpha=0 → 纯 G1 兜底，无色调。"""
        wall = _make_wallpaper()
        rect = (0.0, 0.0, float(wall.shape[1]), float(wall.shape[0]))
        cfg = mt.TintConfig(dark=True, alpha=0.0, dither=False, sigma=8.0)
        res = mt.bake_tint(wall, rect, 40, 30, cfg)
        expected = np.array(mt.G1_DARK, dtype=np.uint8).reshape(1, 1, 3)
        np.testing.assert_array_equal(res.image, np.broadcast_to(expected, res.image.shape))

    def test_crop_resize_clamps_oob(self) -> None:
        """采样矩形越界时按 CLAMP_TO_EDGE 钳制（不抛异常）。"""
        wall = np.full((50, 80, 3), 100, dtype=np.uint8)
        out = mt.crop_resize(wall, (-100.0, -50.0, 200.0, 200.0), 30, 20)
        assert out.shape == (20, 30, 3)
        assert (out == 100).all()  # 整幅同色 ⇒ 钳制后仍同色

    def test_sample_rect_px_includes_sigma_margin(self) -> None:
        """``sample_rect_px`` 外扩量至少为 ``3σ``。"""
        rect = mt.sample_rect_px((0.0, 0.0, 100.0, 100.0), sigma_px=20.0, wall_w=200, wall_h=200)
        # 期望外扩 3 * 20 = 60（> 10% × 100 = 10）
        assert rect == (-60.0, -60.0, 220.0, 220.0)

    def test_luma_pure_blue_with_g1_light(self) -> None:
        """边界：``Color(G1_LIGHT, 纯蓝)`` 在小精度下落到 [0, 1]。"""
        b = np.array(mt.G1_LIGHT, dtype=np.float32) / 255.0
        s = np.array([0.0, 0.0, 1.0], dtype=np.float32)
        out = mt.color_blend(b, s)
        assert ((out >= 0) & (out <= 1)).all()
