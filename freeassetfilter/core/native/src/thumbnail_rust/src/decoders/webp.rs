//! WebP 容器 + VP8L 无损解码器（todo 18 实现；依赖 todo 2 bitreader/inflate，
//! VP8 有损块委托 `vp8.rs`）。
//!
//! 职责：RIFF/WEBP 四块解析（VP8 / VP8L / VP8X / ALPH / ANIM）；VP8L 无损
//! 全量（RLE + Huffman 编码、预测/颜色索引/颜色缓存/降色变换、Huffman 树、
//! 转 ARGB）；VP8 有损块路由到 todo 19。
//!
//! 本文件为骨架：todo 18 中实现 `decode_webp` 与容器分块。