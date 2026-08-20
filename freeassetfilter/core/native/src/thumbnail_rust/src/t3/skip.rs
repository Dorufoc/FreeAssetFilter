//! T3 智能识别跳过（todo 25 实现）。
//!
//! 职责：T3 通则——`STATUS_UNSUPPORTED`（RAW 系 cr2/cr3/nef/arw/dng/orf/raf/
//! rw2/pef/x3f、psb、xcf、svg、jxr、icns-jp2、dds-bc7 未实现等）与
//! `STATUS_TOO_LARGE`（解码尺寸/内存超限）及一切解码失败统一入 errorlog
//! （path/format/status/message/timestamp）并快速返回；各失败路径不 panic
//! 而返回结构化状态。
//!
//! 本文件为骨架：todo 25 中实现跳过判定谓词与错误闭环接线。