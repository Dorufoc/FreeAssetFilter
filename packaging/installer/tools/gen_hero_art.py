#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从设计稿 SVG 生成 Sopeek 词标的 Direct2D 路径数据（C++ 片段）。

设计稿：`src/sopeek/resources/icons/install_design/英雄页.svg`（1920x1080 artboard）
里的 `组_48`（Sopeek 词标，9 条 path，全部 fill #091935）。

输出的 `.inc` 被 `src/render/hero_art.cpp` 以 `#include` 方式引入，内容是
`HeroArtCmd` 数组：每个元素 = {verb, x1,y1,x2,y2,x3,y3}，verb 0=Move 1=Cubic 2=Close。
所有坐标是**组局部坐标**（已叠加各子元素的 translate，未叠加 组_48 自身的
translate），绘制时由调用方平移/缩放。

用法（仓库根目录）：

    .venv\\Scripts\\python.exe packaging/installer/tools/gen_hero_art.py

重新生成后与旧文件对比即可看出设计稿是否变化；本脚本不参与构建（.inc 已入库）。
"""

import math
import os
import re
import sys
import xml.etree.ElementTree as ET

NS = "{http://www.w3.org/2000/svg}"
WORDMARK_GROUP_ID = "组_48"

TOKEN_RE = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")

IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)  # a b c d e f


def mat_mul(m, n):
    """返回 m ∘ n（先应用 n，再应用 m）。"""
    a1, b1, c1, d1, e1, f1 = m
    a2, b2, c2, d2, e2, f2 = n
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def apply(m, x, y):
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


def parse_transform(text):
    if not text:
        return IDENTITY
    total = IDENTITY
    for name, args in re.findall(r"([a-zA-Z]+)\s*\(([^)]*)\)", text):
        vals = [float(v) for v in re.findall(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?", args)]
        name = name.strip()
        if name == "translate":
            tx = vals[0] if vals else 0.0
            ty = vals[1] if len(vals) > 1 else 0.0
            m = (1.0, 0.0, 0.0, 1.0, tx, ty)
        elif name == "scale":
            sx = vals[0] if vals else 1.0
            sy = vals[1] if len(vals) > 1 else sx
            m = (sx, 0.0, 0.0, sy, 0.0, 0.0)
        elif name == "rotate":
            deg = vals[0] if vals else 0.0
            rad = math.radians(deg)
            cs, sn = math.cos(rad), math.sin(rad)
            m = (cs, sn, -sn, cs, 0.0, 0.0)
            if len(vals) >= 3:
                cx, cy = vals[1], vals[2]
                m = mat_mul(mat_mul((1.0, 0.0, 0.0, 1.0, cx, cy), m),
                            (1.0, 0.0, 0.0, 1.0, -cx, -cy))
        elif name == "matrix":
            m = tuple(vals[:6]) if len(vals) >= 6 else IDENTITY
        else:
            m = IDENTITY
        total = mat_mul(total, m)
    return total


def arc_to_cubics(x0, y0, rx, ry, x_rot_deg, large_arc, sweep, x1, y1):
    """SVG 端点参数化弧 → 若干三次贝塞尔（SVG 规范 F.6.5 标准实现）。"""
    if rx == 0.0 or ry == 0.0:
        return [((x0 + (x1 - x0) / 3.0, y0 + (y1 - y0) / 3.0),
                 (x0 + 2.0 * (x1 - x0) / 3.0, y0 + 2.0 * (y1 - y0) / 3.0),
                 (x1, y1))]
    rx, ry = abs(rx), abs(ry)
    phi = math.radians(x_rot_deg)
    cs, sn = math.cos(phi), math.sin(phi)

    dx2 = (x0 - x1) / 2.0
    dy2 = (y0 - y1) / 2.0
    x1p = cs * dx2 + sn * dy2
    y1p = -sn * dx2 + cs * dy2

    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1.0:
        scale = math.sqrt(lam)
        rx *= scale
        ry *= scale

    sign = -1.0 if large_arc == sweep else 1.0
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    coef = sign * math.sqrt(max(0.0, num / den)) if den else 0.0
    cxp = coef * rx * y1p / ry
    cyp = -coef * ry * x1p / rx

    cx = cs * cxp - sn * cyp + (x0 + x1) / 2.0
    cy = sn * cxp + cs * cyp + (y0 + y1) / 2.0

    def ang(ux, uy, vx, vy):
        dot = ux * vx + uy * vy
        norm = math.hypot(ux, uy) * math.hypot(vx, vy)
        if norm == 0.0:
            return 0.0
        val = max(-1.0, min(1.0, dot / norm))
        a = math.acos(val)
        if ux * vy - uy * vx < 0.0:
            a = -a
        return a

    theta1 = ang(1.0, 0.0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dtheta = ang((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and dtheta > 0.0:
        dtheta -= 2.0 * math.pi
    elif sweep and dtheta < 0.0:
        dtheta += 2.0 * math.pi

    segments = max(1, int(math.ceil(abs(dtheta) / (math.pi / 2.0))))
    step = dtheta / segments
    k = 4.0 / 3.0 * math.tan(step / 4.0)

    out = []
    for i in range(segments):
        t1 = theta1 + i * step
        t2 = t1 + step
        c1, s1 = math.cos(t1), math.sin(t1)
        c2, s2 = math.cos(t2), math.sin(t2)

        def point(c, s):
            return (cs * rx * c - sn * ry * s + cx, sn * rx * c + cs * ry * s + cy)

        p1 = point(c1, s1)
        p2 = point(c2, s2)
        d1 = (cs * rx * -s1 - sn * ry * c1, sn * rx * -s1 + cs * ry * c1)
        d2 = (cs * rx * -s2 - sn * ry * c2, sn * rx * -s2 + cs * ry * c2)
        ctrl1 = (p1[0] + k * d1[0], p1[1] + k * d1[1])
        ctrl2 = (p2[0] - k * d2[0], p2[1] - k * d2[1])
        out.append((ctrl1, ctrl2, p2))
    return out


def path_to_commands(d, matrix):
    tokens = TOKEN_RE.findall(d)
    cmds = []
    i = 0
    cur = (0.0, 0.0)
    start = (0.0, 0.0)
    prev_cubic_ctrl = None
    prev_quad_ctrl = None
    last_cmd = None

    def num():
        nonlocal i
        v = float(tokens[i])
        i += 1
        return v

    def next_is_number():
        return i < len(tokens) and tokens[i] not in "MmLlHhVvCcSsQqTtAaZz"

    while i < len(tokens):
        tok = tokens[i]
        if tok in "MmLlHhVvCcSsQqTtAaZz":
            cmd = tok
            i += 1
        else:
            if last_cmd in ("M", "L"):
                cmd = "L" if last_cmd == "M" else last_cmd
            elif last_cmd in ("m", "l"):
                cmd = "l" if last_cmd == "m" else last_cmd
            else:
                cmd = last_cmd
        rel = cmd.islower()
        up = cmd.upper()

        if up == "Z":
            cmds.append((2, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
            cur = start
            prev_cubic_ctrl = prev_quad_ctrl = None
            last_cmd = cmd
            continue

        if up == "M":
            x, y = num(), num()
            if rel:
                x, y = cur[0] + x, cur[1] + y
            a = apply(matrix, x, y)
            cmds.append((0, a[0], a[1], 0.0, 0.0, 0.0, 0.0))
            cur = start = (x, y)
            prev_cubic_ctrl = prev_quad_ctrl = None
            last_cmd = "M" if not rel else "m"
            continue

        if up == "L":
            x, y = num(), num()
            if rel:
                x, y = cur[0] + x, cur[1] + y
            a = apply(matrix, x, y)
            cmds.append((1, cur[0] if False else apply(matrix, cur[0], cur[1])[0],
                         apply(matrix, cur[0], cur[1])[1], 0.0, 0.0, 0.0, 0.0))
            # 用「当前点 → 目标点」的直线，以三次贝塞尔退化表达（控制点取 1/3、2/3）。
            p0 = apply(matrix, cur[0], cur[1])
            cmds[-1] = (1, p0[0] + (a[0] - p0[0]) / 3.0, p0[1] + (a[1] - p0[1]) / 3.0,
                        p0[0] + 2.0 * (a[0] - p0[0]) / 3.0, p0[1] + 2.0 * (a[1] - p0[1]) / 3.0,
                        a[0], a[1])
            cur = (x, y)
            prev_cubic_ctrl = prev_quad_ctrl = None
            last_cmd = "L" if not rel else "l"
            continue

        if up == "H":
            x = num()
            x = cur[0] + x if rel else x
            y = cur[1]
            p0 = apply(matrix, cur[0], cur[1])
            a = apply(matrix, x, y)
            cmds.append((1, p0[0] + (a[0] - p0[0]) / 3.0, p0[1] + (a[1] - p0[1]) / 3.0,
                         p0[0] + 2.0 * (a[0] - p0[0]) / 3.0, p0[1] + 2.0 * (a[1] - p0[1]) / 3.0,
                         a[0], a[1]))
            cur = (x, y)
            prev_cubic_ctrl = prev_quad_ctrl = None
            last_cmd = "H" if not rel else "h"
            continue

        if up == "V":
            y = num()
            y = cur[1] + y if rel else y
            x = cur[0]
            p0 = apply(matrix, cur[0], cur[1])
            a = apply(matrix, x, y)
            cmds.append((1, p0[0] + (a[0] - p0[0]) / 3.0, p0[1] + (a[1] - p0[1]) / 3.0,
                         p0[0] + 2.0 * (a[0] - p0[0]) / 3.0, p0[1] + 2.0 * (a[1] - p0[1]) / 3.0,
                         a[0], a[1]))
            cur = (x, y)
            prev_cubic_ctrl = prev_quad_ctrl = None
            last_cmd = "V" if not rel else "v"
            continue

        if up == "C":
            x1, y1 = num(), num()
            x2, y2 = num(), num()
            x, y = num(), num()
            if rel:
                x1, y1 = cur[0] + x1, cur[1] + y1
                x2, y2 = cur[0] + x2, cur[1] + y2
                x, y = cur[0] + x, cur[1] + y
            c1 = apply(matrix, x1, y1)
            c2 = apply(matrix, x2, y2)
            e = apply(matrix, x, y)
            cmds.append((1, c1[0], c1[1], c2[0], c2[1], e[0], e[1]))
            prev_cubic_ctrl = (x2, y2)
            prev_quad_ctrl = None
            cur = (x, y)
            last_cmd = "C" if not rel else "c"
            continue

        if up == "S":
            x2, y2 = num(), num()
            x, y = num(), num()
            if rel:
                x2, y2 = cur[0] + x2, cur[1] + y2
                x, y = cur[0] + x, cur[1] + y
            if prev_cubic_ctrl is None:
                x1, y1 = cur
            else:
                x1 = 2.0 * cur[0] - prev_cubic_ctrl[0]
                y1 = 2.0 * cur[1] - prev_cubic_ctrl[1]
            c1 = apply(matrix, x1, y1)
            c2 = apply(matrix, x2, y2)
            e = apply(matrix, x, y)
            cmds.append((1, c1[0], c1[1], c2[0], c2[1], e[0], e[1]))
            prev_cubic_ctrl = (x2, y2)
            prev_quad_ctrl = None
            cur = (x, y)
            last_cmd = "S" if not rel else "s"
            continue

        if up == "Q":
            x1, y1 = num(), num()
            x, y = num(), num()
            if rel:
                x1, y1 = cur[0] + x1, cur[1] + y1
                x, y = cur[0] + x, cur[1] + y
            q = (x1, y1)
            c1 = (cur[0] + 2.0 / 3.0 * (q[0] - cur[0]), cur[1] + 2.0 / 3.0 * (q[1] - cur[1]))
            c2 = (x + 2.0 / 3.0 * (q[0] - x), y + 2.0 / 3.0 * (q[1] - y))
            a1 = apply(matrix, c1[0], c1[1])
            a2 = apply(matrix, c2[0], c2[1])
            e = apply(matrix, x, y)
            cmds.append((1, a1[0], a1[1], a2[0], a2[1], e[0], e[1]))
            prev_quad_ctrl = (x1, y1)
            prev_cubic_ctrl = None
            cur = (x, y)
            last_cmd = "Q" if not rel else "q"
            continue

        if up == "T":
            x, y = num(), num()
            if rel:
                x, y = cur[0] + x, cur[1] + y
            if prev_quad_ctrl is None:
                q = cur
            else:
                q = (2.0 * cur[0] - prev_quad_ctrl[0], 2.0 * cur[1] - prev_quad_ctrl[1])
            c1 = (cur[0] + 2.0 / 3.0 * (q[0] - cur[0]), cur[1] + 2.0 / 3.0 * (q[1] - cur[1]))
            c2 = (x + 2.0 / 3.0 * (q[0] - x), y + 2.0 / 3.0 * (q[1] - y))
            a1 = apply(matrix, c1[0], c1[1])
            a2 = apply(matrix, c2[0], c2[1])
            e = apply(matrix, x, y)
            cmds.append((1, a1[0], a1[1], a2[0], a2[1], e[0], e[1]))
            prev_quad_ctrl = q
            prev_cubic_ctrl = None
            cur = (x, y)
            last_cmd = "T" if not rel else "t"
            continue

        if up == "A":
            rx, ry, rot = num(), num(), num()
            large = int(num())
            sweep = int(num())
            x, y = num(), num()
            if rel:
                x, y = cur[0] + x, cur[1] + y
            for c1, c2, e in arc_to_cubics(cur[0], cur[1], rx, ry, rot, large, sweep, x, y):
                a1 = apply(matrix, c1[0], c1[1])
                a2 = apply(matrix, c2[0], c2[1])
                ae = apply(matrix, e[0], e[1])
                cmds.append((1, a1[0], a1[1], a2[0], a2[1], ae[0], ae[1]))
            cur = (x, y)
            prev_cubic_ctrl = prev_quad_ctrl = None
            last_cmd = "A" if not rel else "a"
            continue

        raise SystemExit("unsupported path command: %s" % cmd)

    return cmds


def collect(el, matrix, out):
    for child in list(el):
        tag = child.tag.replace(NS, "")
        m = mat_mul(matrix, parse_transform(child.get("transform")))
        if tag == "g":
            collect(child, m, out)
        elif tag == "path":
            d = child.get("d")
            if d:
                out.extend(path_to_commands(d, m))


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.abspath(os.path.join(here, "..", "..", ".."))
    svg_path = os.path.join(repo, "src", "sopeek", "resources", "icons", "install_design", "英雄页.svg")
    out_path = os.path.join(repo, "packaging", "installer", "src", "render", "hero_art_paths.inc")

    tree = ET.parse(svg_path)
    root = tree.getroot()

    def find(handle, gid):
        for node in handle.iter():
            if node.get("id") == gid:
                return node
        return None

    group = find(root, WORDMARK_GROUP_ID)
    if group is None:
        raise SystemExit("group %s not found in %s" % (WORDMARK_GROUP_ID, svg_path))

    # 组局部坐标：不叠加 组_48 自身的 translate（绘制时由调用方平移/缩放）。
    cmds = []
    collect(group, IDENTITY, cmds)

    xs = [c[i] for c in cmds if c[0] != 2 for i in (1, 3, 5)]
    ys = [c[i] for c in cmds if c[0] != 2 for i in (2, 4, 6)]
    bbox = (min(xs), min(ys), max(xs), max(ys))

    lines = []
    lines.append("// AUTO-GENERATED by packaging/installer/tools/gen_hero_art.py -- do not edit by hand.")
    lines.append("// Source: src/sopeek/resources/icons/install_design/英雄页.svg (group 组_48, 9 paths, fill #091935).")
    lines.append("// verb: 0 = MoveTo(x1,y1) / 1 = CubicTo(x1,y1,x2,y2,x3,y3) / 2 = Close.")
    lines.append("// Wordmark bbox in group-local units: %.3f %.3f %.3f %.3f (w=%.3f h=%.3f)" % (
        bbox[0], bbox[1], bbox[2], bbox[3], bbox[2] - bbox[0], bbox[3] - bbox[1]))
    lines.append("")
    for c in cmds:
        if c[0] == 2:
            lines.append("    {2, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f},")
        elif c[0] == 0:
            lines.append("    {0, %.4ff, %.4ff, 0.0f, 0.0f, 0.0f, 0.0f}," % (c[1], c[2]))
        else:
            lines.append("    {1, %.4ff, %.4ff, %.4ff, %.4ff, %.4ff, %.4ff}," % c[1:7])
    lines.append("")
    text = "\n".join(lines)
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)

    print("commands: %d" % len(cmds))
    print("bbox: %.3f %.3f %.3f %.3f (w=%.3f h=%.3f)" % (
        bbox[0], bbox[1], bbox[2], bbox[3], bbox[2] - bbox[0], bbox[3] - bbox[1]))
    print("wrote: %s (%d bytes)" % (out_path, len(text.encode("utf-8"))))


if __name__ == "__main__":
    sys.exit(main())
