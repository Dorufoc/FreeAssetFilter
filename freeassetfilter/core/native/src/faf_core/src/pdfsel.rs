//! `pdfsel.rs` —— PDF 选区逐词过滤（todo 18：`faf_pdf_select_words`）。
//!
//! 语义 oracle：`freeassetfilter/services/pdf_document_view.py`
//! `get_text_selection`（L616-745）——归一化矩形、逐页范围、Y 重叠、smart
//! x-bound（`dragging_down`/`touches_top`/`touches_bottom`/`strictly_inside`）
//! 过滤、`sort((page,block,line,word_no))`。**`PdfDocument.get_text_words`
//!（PyMuPDF，已原生）保留在 Python**——Rust 只吃词表 JSON + 选区参数 JSON，
//! 返回选中词条目 JSON 数组（条目携带 page-space bbox，供 todo 19 重建
//! `_cached_sel_words` / `_refresh_selection_rects`）。
//!
//! **不做文件 I/O、不 panic**：纯几何过滤 + 排序，词表与选区参数全部经
//! JSON 传入（Python 侧序列化）。
//!
//! # JSON 契约（与 todo 19 接线对齐）
//!
//! 1. **词表 `words_json`**：PyMuPDF `get_text_words` 产物平铺数组，每词一个
//!   对象：
//!   ```json
//!   {"page":0,"block":0,"line":0,"word_no":0,"text":"alpha",
//!    "x0":71.8,"y0":99.7,"x1":112.1,"y1":113.7}
//!   ```
//!   `page` 为页索引；`x0/y0/x1/y1` 为 **page-space**（页内 PDF 点）包围盒，
//!   与 `get_text_selection` 消费的 `(wx0,wy0,wx1,wy1)` 一致。
//! 2. **选区 `selection_json`**：归一化前的原始拖拽参数 + 页高表（Rust 用
//!   页高重算 `_accum_page_heights` 并做 `absolute_to_page` 二分，见
//!   `pdf_document_view.py:347-379`）：
//!   ```json
//!   {"begin_abs_x":72.0,"begin_abs_y":100.0,"end_abs_x":401.5,"end_abs_y":198.0,
//!    "page_heights":[792.0,792.0,792.0]}
//!   ```
//!   ⚠️ x-bound 过滤用的是**原始** `begin_abs_x`/`end_abs_x`（oracle L711/L715
//!   等处直接用入参），不是归一化 `x0/x1`——必须原样透传。
//! 3. **返回值**：选中词条目 JSON 数组（键同词表，`page/block/line/word_no/`
//!   `text/x0/y0/x1/y1`），按 `(page,block,line,word_no)` 稳定升序。
//!
//! # 与 oracle 的逐语义对应
//!
//! - **归一化矩形**：`x0=min(bx,ex)`、`x1=max(bx,ex)`、`y0/y1` 同（L655-658）。
//! - **逐页范围**：`absolute_to_page`（L660-661）——`page_top =
//!   accum[p] - heights[p]`、`y_within = clamp(abs_y - page_top)`、页索引取
//!   `bisect_left(accum, abs_y)` 并钳制到末页。
//! - **Y 重叠**（L684-685）：`wy0 < sel_y1 && wy1 > sel_y0`，其中页内窗口
//!   `sel_y0 = max(y0 - page_top, 0)`、`sel_y1 = min(y1 - page_top, h_p)`
//!   （L676-677）。
//! - **smart x-bound**（L695-728）：绝对 Y 谓词
//!   `touches_top = ab0 < y0 < ab1`、`touches_bottom = ab0 < y1 < ab1`、
//!   `strictly_inside = ab0 >= y0 && ab1 <= y1`；中间行（strictly_inside）无视
//!   x；首行/末行按拖拽方向分别以 `wx1 > begin_abs_x` 或 `wx0 < end_abs_x`
//!   过滤；同时触碰两边界（罕见大词）走 else 直接接受。
//! - **排序**（L735）：`(page, block, line, word_no)` 稳定升序。
//!
//! 词表条目超出选区页范围（`page` 不在 `[start_page, end_page]` 或越界/负数）
//! 一律跳过——健壮而非报错（与 `get_text_words` 的合法产物一致）。
//!
//! # 已知波动（accepted-diff，证据 task-18-pdf.txt）
//!
//! serde_json 的 `f64` 解析**非严格正确舍入**（`"187.94801330566406"` 实测
//! 被读到 +1 ULP 的邻居值，Ryu 随即输出 `"187.9480133056641"`）。因此返回
//! 条目的 `x0/y0/x1/y1` 与 Python 原始 `get_text_words` 浮点值在部分值上差
//! ≤1 ULP。选中词**序列与文本逐字节一致**（验收基线）；bbox 仅供 todo 19 建
//! 索引用，todo 19/20 的 `_cached_sel_words` 与矩形仍取 Python 自身权威值，
//! 此漂移不传播到选区矩形。已计入计划 ≤2 accepted-diffs 配额。

use serde_json::{Map, Value};

use crate::STATUS_INVALID_ARG;

/// 选区参数（归一化前的原始拖拽坐标 + 页高表）。
struct Selection {
    begin_abs_x: f64,
    begin_abs_y: f64,
    end_abs_x: f64,
    end_abs_y: f64,
    page_heights: Vec<f64>,
}

/// 词条目（与 PyMuPDF `get_text_words` 的
/// `(x0,y0,x1,y1,word,block,line,word_no)` 对应；坐标界：page-space）。
struct Word {
    page: i64,
    block: i64,
    line: i64,
    word_no: i64,
    text: String,
    x0: f64,
    y0: f64,
    x1: f64,
    y1: f64,
}

/// 读取对象数值字段（缺键/非数字 → `None`）。
fn obj_f64(v: &Map<String, Value>, key: &str) -> Option<f64> {
    v.get(key).and_then(Value::as_f64)
}

/// 读取对象整数字段（缺键/非整数 → `None`）。block/line/word_no/page 契约上
/// 为整数（PyMuPDF 返回 Python int），非整数按契约违例处理（回退 Python 路径）。
fn obj_int(v: &Map<String, Value>, key: &str) -> Option<i64> {
    v.get(key).and_then(Value::as_i64)
}

/// 解析单个词对象（缺键/类型错误 → `None`）。
fn word_from_value(v: &Value) -> Option<Word> {
    let o = v.as_object()?;
    Some(Word {
        page: obj_int(o, "page")?,
        block: obj_int(o, "block")?,
        line: obj_int(o, "line")?,
        word_no: obj_int(o, "word_no")?,
        text: o.get("text")?.as_str()?.to_string(),
        x0: obj_f64(o, "x0")?,
        y0: obj_f64(o, "y0")?,
        x1: obj_f64(o, "x1")?,
        y1: obj_f64(o, "y1")?,
    })
}

/// 解析选区参数对象（缺键/类型错误 → `None`）。
fn selection_from_value(v: &Value) -> Option<Selection> {
    let o = v.as_object()?;
    let page_heights: Vec<f64> = o
        .get("page_heights")?
        .as_array()?
        .iter()
        .map(Value::as_f64)
        .collect::<Option<Vec<_>>>()?;
    Some(Selection {
        begin_abs_x: obj_f64(o, "begin_abs_x")?,
        begin_abs_y: obj_f64(o, "begin_abs_y")?,
        end_abs_x: obj_f64(o, "end_abs_x")?,
        end_abs_y: obj_f64(o, "end_abs_y")?,
        page_heights,
    })
}

/// 复刻 Python `bisect.bisect_left`（`pdf_document_view.py:367`）：
/// 返回 `a` 中首个满足 `a[i] >= x` 的位置（`a[..i] 全部 < x`）。
fn bisect_left(a: &[f64], x: f64) -> usize {
    a.partition_point(|v| *v < x)
}

/// 词 → JSON 条目对象（键与词表一致）。
fn json_obj(w: &Word) -> Value {
    let m: Map<String, Value> = [
        ("page".to_string(), Value::from(w.page)),
        ("block".to_string(), Value::from(w.block)),
        ("line".to_string(), Value::from(w.line)),
        ("word_no".to_string(), Value::from(w.word_no)),
        ("text".to_string(), Value::from(w.text.clone())),
        ("x0".to_string(), Value::from(w.x0)),
        ("y0".to_string(), Value::from(w.y0)),
        ("x1".to_string(), Value::from(w.x1)),
        ("y1".to_string(), Value::from(w.y1)),
    ]
    .into_iter()
    .collect();
    Value::Object(m)
}

/// 按选区过滤词表为选中词序列（todo 18 实现）。
///
/// 成功：选中词条目 JSON 数组（`sort((page,block,line,word_no))`，稳定）；
/// 失败（JSON 非法 / 结构缺键 / 类型错误）：`Err(STATUS_INVALID_ARG)`——
/// FFI 侧返回 null、Python 回退自身选区过滤，不 panic。空选区 / 无页返回
/// `[]`（与 oracle 空文档早退语义一致）。
pub fn select_words_impl(
    words_json: &str,
    selection_json: &str,
) -> Result<Value, i32> {
    let words_val: Value =
        serde_json::from_str(words_json).map_err(|_| STATUS_INVALID_ARG)?;
    let sel_val: Value =
        serde_json::from_str(selection_json).map_err(|_| STATUS_INVALID_ARG)?;

    let words: Vec<Word> = words_val
        .as_array()
        .ok_or(STATUS_INVALID_ARG)?
        .iter()
        .map(word_from_value)
        .collect::<Option<Vec<_>>>()
        .ok_or(STATUS_INVALID_ARG)?;
    let sel = selection_from_value(&sel_val).ok_or(STATUS_INVALID_ARG)?;

    Ok(select_words(&words, &sel))
}

/// 纯几何过滤 + 排序（复刻 `get_text_selection` L654-745）。
fn select_words(words: &[Word], sel: &Selection) -> Value {
    // `_accum_page_heights`（`pdf_document.py:449-458`）：页高运行和。
    let mut accum: Vec<f64> = Vec::with_capacity(sel.page_heights.len());
    let mut running: f64 = 0.0;
    for h in &sel.page_heights {
        running += h;
        accum.push(running);
    }
    // `get_text_selection` 空文档早退（L651-653）→ 空数组。
    if accum.is_empty() {
        return Value::Array(Vec::new());
    }

    // 归一化矩形（L655-658）。⚠️ oracle 亦计算归一化 x0/x1 但过滤用不到——
    // smart x-bound 直接用原始 `begin_abs_x`/`end_abs_x`（L711/L715），故这里
    // 只保留 y 归一化（y0/y1 用于逐页范围与 Y 谓词）。
    let y0: f64 = sel.begin_abs_y.min(sel.end_abs_y);
    let y1: f64 = sel.begin_abs_y.max(sel.end_abs_y);

    // 逐页范围（`absolute_to_page` L367-376 + L660-661），钳制到末页。
    let start_page: usize = bisect_left(&accum, y0).min(accum.len() - 1);
    let end_page: usize = bisect_left(&accum, y1).min(accum.len() - 1);

    // 拖拽方向（L664）。
    let dragging_down: bool = sel.begin_abs_y <= sel.end_abs_y;

    let mut selected: Vec<&Word> = Vec::new();

    for w in words {
        // 词所在页不在选区页范围 / 越界 / 负数 → 跳过。
        let Ok(wp) = usize::try_from(w.page) else {
            continue;
        };
        if wp >= sel.page_heights.len() || wp < start_page || wp > end_page {
            continue;
        }

        // 页内窗口（L676-677）。
        let page_top: f64 = accum[wp] - sel.page_heights[wp];
        let sel_y0: f64 = (y0 - page_top).max(0.0);
        let sel_y1: f64 = (y1 - page_top).min(sel.page_heights[wp]);

        // Y 重叠（L684-685）。
        if !(w.y0 < sel_y1 && w.y1 > sel_y0) {
            continue;
        }

        // smart x-bound（L695-728）。绝对 Y 谓词。
        let w_abs_y0: f64 = w.y0 + page_top;
        let w_abs_y1: f64 = w.y1 + page_top;
        let touches_top: bool = w_abs_y0 < y0 && y0 < w_abs_y1;
        let touches_bottom: bool = w_abs_y0 < y1 && y1 < w_abs_y1;
        let strictly_inside: bool = w_abs_y0 >= y0 && w_abs_y1 <= y1;

        if strictly_inside && !touches_top && !touches_bottom {
            // 中间行——无视 x。
        } else if touches_top && !touches_bottom {
            // 跨选区上边界：上界即拖拽起始行（向下时）或结束行（向上时）。
            let ok: bool = if dragging_down {
                w.x1 > sel.begin_abs_x
            } else {
                w.x0 < sel.end_abs_x
            };
            if !ok {
                continue;
            }
        } else if touches_bottom && !touches_top {
            // 跨选区下边界：下界即拖拽结束行（向下时）或起始行（向上时）。
            let ok: bool = if dragging_down {
                w.x0 < sel.end_abs_x
            } else {
                w.x1 > sel.begin_abs_x
            };
            if !ok {
                continue;
            }
        }
        // else：同时跨两边界（罕见大词）——归一化矩形已由 Y 重叠保证。

        selected.push(w);
    }

    // 稳定排序（L735）。
    selected.sort_by(|a, b| {
        (a.page, a.block, a.line, a.word_no).cmp(&(b.page, b.block, b.line, b.word_no))
    });

    Value::Array(selected.iter().map(|w| json_obj(w)).collect())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    /// 构造词条目 JSON。
    #[allow(clippy::too_many_arguments)]
    fn word(
        page: i64,
        block: i64,
        line: i64,
        wno: i64,
        x0: f64,
        y0: f64,
        x1: f64,
        y1: f64,
        text: &str,
    ) -> Value {
        json!({
            "page": page, "block": block, "line": line, "word_no": wno,
            "text": text,
            "x0": x0, "y0": y0, "x1": x1, "y1": y1,
        })
    }

    /// 构造选区参数 JSON。
    fn sel(bx: f64, by: f64, ex: f64, ey: f64, page_heights: Vec<f64>) -> String {
        serde_json::to_string(&json!({
            "begin_abs_x": bx, "begin_abs_y": by,
            "end_abs_x": ex, "end_abs_y": ey,
            "page_heights": page_heights,
        }))
        .unwrap()
    }

    /// 结果 JSON → 选中词文本序列。
    fn texts(out: &Value) -> Vec<String> {
        out.as_array()
            .unwrap()
            .iter()
            .map(|x| x.get("text").and_then(Value::as_str).unwrap().to_string())
            .collect()
    }

    /// 9 词三行样本（page0，行 y10..20 / y30..40 / y50..60）。
    fn sample_grid() -> String {
        serde_json::to_string(&Value::Array(vec![
            word(0, 0, 0, 0, 0.0, 10.0, 10.0, 20.0, "A"),
            word(0, 0, 0, 1, 10.0, 10.0, 20.0, 20.0, "B"),
            word(0, 0, 0, 2, 20.0, 10.0, 30.0, 20.0, "C"),
            word(0, 0, 1, 0, 0.0, 30.0, 10.0, 40.0, "D"),
            word(0, 0, 1, 1, 10.0, 30.0, 20.0, 40.0, "E"),
            word(0, 0, 1, 2, 20.0, 30.0, 30.0, 40.0, "F"),
            word(0, 0, 2, 0, 0.0, 50.0, 10.0, 60.0, "G"),
            word(0, 0, 2, 1, 10.0, 50.0, 20.0, 60.0, "H"),
            word(0, 0, 2, 2, 20.0, 50.0, 30.0, 60.0, "I"),
        ]))
        .unwrap()
    }

    /// 向下拖拽：首行按 `wx1 > begin_x`、末行按 `wx0 < end_x`、中间行全收。
    #[test]
    fn downward_drag_filters_first_last_line_x_bounds() {
        let out = select_words_impl(&sample_grid(), &sel(15.0, 15.0, 15.0, 55.0, vec![200.0]))
            .unwrap();
        assert_eq!(texts(&out), vec!["B", "C", "D", "E", "F", "G", "H"]);
    }

    /// 向上拖拽：首行（跨上界）按 `wx0 < end_x`、末行（跨下界）按 `wx1 > begin_x`。
    #[test]
    fn upward_drag_filters_first_last_line_x_bounds() {
        let out = select_words_impl(&sample_grid(), &sel(15.0, 55.0, 15.0, 15.0, vec![200.0]))
            .unwrap();
        assert_eq!(texts(&out), vec!["A", "B", "D", "E", "F", "H", "I"]);
    }

    /// 首末行 x 边界**严格比较**：`wx1 == begin_x` 排除、`wx0 == end_x` 排除。
    #[test]
    fn x_bound_filters_use_strict_inequalities() {
        let words_json = serde_json::to_string(&Value::Array(vec![
            // 首行（y10..20）：J.wx1 == 15 → 排除；K.wx1 == 25 > 15 → 保留。
            word(0, 0, 0, 0, 10.0, 10.0, 15.0, 20.0, "J"),
            word(0, 0, 0, 1, 15.0, 10.0, 25.0, 20.0, "K"),
            // 末行（y30..40）：P.wx0 == 15 → 排除；Q.wx0 == 5 < 15 → 保留。
            word(0, 0, 1, 0, 15.0, 30.0, 25.0, 40.0, "P"),
            word(0, 0, 1, 1, 5.0, 30.0, 15.0, 40.0, "Q"),
        ]))
        .unwrap();
        let out = select_words_impl(&words_json, &sel(15.0, 15.0, 15.0, 35.0, vec![200.0]))
            .unwrap();
        assert_eq!(texts(&out), vec!["K", "Q"]);
    }

    /// 跨页：选区覆盖 page0 顶部一行 + page1 中部行；越界词与 page1 下方词剔除；
    /// 输入乱序仍按 (page,block,line,word_no) 稳定排序。
    #[test]
    fn cross_page_selection_sorts_by_page() {
        let words_json = serde_json::to_string(&Value::Array(vec![
            word(1, 0, 0, 1, 10.0, 5.0, 20.0, 15.0, "M"),
            word(1, 0, 1, 0, 20.0, 25.0, 40.0, 35.0, "FAR"),
            word(0, 0, 0, 0, 0.0, 10.0, 10.0, 20.0, "L"),
            word(0, 0, 0, 1, 10.0, 10.0, 20.0, 20.0, "R"),
            word(1, 0, 0, 0, 20.0, 5.0, 30.0, 15.0, "N"),
            word(1, 0, 1, 1, 45.0, 25.0, 55.0, 35.0, "OUT2"),
        ]))
        .unwrap();
        // begin=(5,15) → end=(5,215)：y0=15（page0），y1=215（page1，accum=[200,350]）。
        let out =
            select_words_impl(&words_json, &sel(5.0, 15.0, 5.0, 215.0, vec![200.0, 150.0]))
                .unwrap();
        // page1 上 N.word_no=0 先于 M.word_no=1 → [L, R, N, M]。
        assert_eq!(texts(&out), vec!["L", "R", "N", "M"]);
    }

    /// 空选区 / 无页 / 词不在选区垂直范围 → 空数组，不 panic。
    #[test]
    fn empty_selection_returns_empty_array() {
        // 空词表 + 正常选区。
        let out = select_words_impl("[]", &sel(0.0, 0.0, 100.0, 100.0, vec![200.0])).unwrap();
        assert_eq!(out.as_array().unwrap().len(), 0);

        // 词在选区范围外（零高选区 y0==y1==5，词 y10..20）。
        let out =
            select_words_impl(&sample_grid(), &sel(0.0, 5.0, 100.0, 5.0, vec![200.0])).unwrap();
        assert_eq!(out.as_array().unwrap().len(), 0);

        // 空页高表 → 空数组（oracle `get_text_selection` 空文档早退）。
        let out = select_words_impl("[]", &sel(0.0, 0.0, 10.0, 10.0, vec![])).unwrap();
        assert_eq!(out.as_array().unwrap().len(), 0);
        let out = select_words_impl(&sample_grid(), &sel(0.0, 0.0, 10.0, 10.0, vec![])).unwrap();
        assert_eq!(out.as_array().unwrap().len(), 0);
    }

    /// 词 page 越界 / 负数：稳健跳过，不影响其它词。
    #[test]
    fn words_on_pages_outside_page_range_are_ignored() {
        let words_json = serde_json::to_string(&Value::Array(vec![
            word(5, 0, 0, 0, 0.0, 10.0, 10.0, 20.0, "BAD"),
            word(-1, 0, 0, 0, 0.0, 10.0, 10.0, 20.0, "BAD2"),
            word(0, 0, 0, 0, 0.0, 10.0, 10.0, 20.0, "OK"),
        ]))
        .unwrap();
        let out = select_words_impl(&words_json, &sel(0.0, 0.0, 0.0, 100.0, vec![200.0])).unwrap();
        assert_eq!(texts(&out), vec!["OK"]);
    }

    /// 同时跨选区上下边界的词（覆盖整个选区）直接接受，无视 x 过滤。
    #[test]
    fn word_spanning_both_boundaries_is_accepted() {
        let words_json = serde_json::to_string(&Value::Array(vec![word(
            0, 0, 0, 0, 0.0, 5.0, 10.0, 45.0, "SPAN",
        )]))
        .unwrap();
        // begin=(50,10) → end=(50,40)：y0=10, y1=40；词 y5..45 完全覆盖。
        let out = select_words_impl(&words_json, &sel(50.0, 10.0, 50.0, 40.0, vec![200.0]))
            .unwrap();
        assert_eq!(texts(&out), vec!["SPAN"]);
    }

    /// 词表/选区 JSON 非法（语法/结构缺键/类型错）→ `STATUS_INVALID_ARG`，不 panic。
    #[test]
    fn malformed_json_returns_invalid_arg() {
        let valid_sel = sel(0.0, 0.0, 10.0, 10.0, vec![200.0]);

        assert_eq!(
            select_words_impl("not json", "{}").unwrap_err(),
            STATUS_INVALID_ARG
        );
        assert_eq!(
            select_words_impl("[]", "not json").unwrap_err(),
            STATUS_INVALID_ARG
        );
        // 选区缺键。
        assert_eq!(select_words_impl("[]", "{}").unwrap_err(), STATUS_INVALID_ARG);
        // 词缺键。
        assert_eq!(
            select_words_impl(r#"[{"page":0}]"#, &valid_sel).unwrap_err(),
            STATUS_INVALID_ARG
        );
        // page_heights 含非数字成员。
        assert_eq!(
            select_words_impl(
                "[]",
                r#"{"begin_abs_x":0,"begin_abs_y":0,"end_abs_x":0,"end_abs_y":0,"page_heights":[{}]}"#
            )
            .unwrap_err(),
            STATUS_INVALID_ARG
        );
        // words_json 非数组。
        assert_eq!(
            select_words_impl("{}", &valid_sel).unwrap_err(),
            STATUS_INVALID_ARG
        );
    }

    /// 选区页范围钳制：拖拽超出末页仍返回末页词（不越界、不 panic）。
    #[test]
    fn selection_beyond_last_page_clamps_to_final_page() {
        let words_json = serde_json::to_string(&Value::Array(vec![
            word(0, 0, 0, 0, 0.0, 10.0, 10.0, 20.0, "P0A"),
            word(1, 0, 0, 0, 0.0, 10.0, 10.0, 20.0, "P1A"),
        ]))
        .unwrap();
        // y1 = 1e9 >> 总高 350 → end_page 钳制到 page1。
        let out = select_words_impl(&words_json, &sel(0.0, 0.0, 0.0, 1e9, vec![200.0, 150.0]))
            .unwrap();
        // page1 词 sel_y1 = min(1e9-200, 150) = 150 → 词 y10..20 重叠 →
        // strictly_inside → 保留；page0 词同理保留。
        assert_eq!(texts(&out), vec!["P0A", "P1A"]);
    }
}