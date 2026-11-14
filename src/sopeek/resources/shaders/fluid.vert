#version 450

// 流体背景顶点着色器：全屏两个三角形。
// 该源码经 Qt Shader Baker 编译为 fluid.vert.qsb；片元着色器见 fluid.frag
// （对应 fluid.frag.qsb）。编译命令（每个文件单独执行一次）：
//   pyside6-qsb --glsl "330" --hlsl "50" -o fluid.vert.qsb fluid.vert
//   pyside6-qsb --glsl "330" --hlsl "50" -o fluid.frag.qsb fluid.frag

layout(location = 0) in vec3 a_position;
layout(location = 0) out vec2 v_uv;

void main()
{
    v_uv = a_position.xy * 0.5 + 0.5;
    gl_Position = vec4(a_position, 1.0);
}
