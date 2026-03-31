use std::cmp::Ordering;
use std::ffi::{c_char, CString};
use std::slice;

const VERSION: &str = "Rust 1.1.0";

#[repr(C)]
pub struct LabResult {
    pub l: f32,
    pub a: f32,
    pub b: f32,
}

#[repr(C)]
pub struct RgbResult {
    pub r: u8,
    pub g: u8,
    pub b: u8,
}

#[derive(Clone, Copy, Debug)]
struct Rgb {
    r: u8,
    g: u8,
    b: u8,
}

#[derive(Clone, Copy, Debug)]
struct Lab {
    l: f32,
    a: f32,
    b: f32,
}

#[derive(Clone, Debug)]
struct Cluster {
    centroid: Lab,
    size: usize,
}

#[no_mangle]
pub extern "C" fn color_extractor_get_version() -> *mut c_char {
    string_to_ptr(VERSION.to_string())
}

#[no_mangle]
pub extern "C" fn color_extractor_free_string(ptr: *mut c_char) {
    if ptr.is_null() {
        return;
    }
    unsafe {
        let _ = CString::from_raw(ptr);
    }
}

#[no_mangle]
pub extern "C" fn color_extractor_rgb_to_lab(r: u8, g: u8, b: u8) -> LabResult {
    let lab = rgb_to_lab(Rgb { r, g, b });
    LabResult {
        l: lab.l,
        a: lab.a,
        b: lab.b,
    }
}

#[no_mangle]
pub extern "C" fn color_extractor_lab_to_rgb(l: f32, a: f32, b: f32) -> RgbResult {
    let rgb = lab_to_rgb(Lab { l, a, b });
    RgbResult {
        r: rgb.r,
        g: rgb.g,
        b: rgb.b,
    }
}

#[no_mangle]
pub extern "C" fn color_extractor_ciede2000(
    l1: f32,
    a1: f32,
    b1: f32,
    l2: f32,
    a2: f32,
    b2: f32,
) -> f32 {
    ciede2000(
        Lab { l: l1, a: a1, b: b1 },
        Lab { l: l2, a: a2, b: b2 },
    )
}

#[no_mangle]
pub extern "C" fn color_extractor_extract_colors(
    data_ptr: *const u8,
    data_len: usize,
    num_colors: i32,
    min_distance: f32,
    max_image_size: i32,
) -> *mut c_char {
    let result = extract_colors_internal(data_ptr, data_len, num_colors, min_distance, max_image_size);
    match result {
        Ok(colors) => {
            let payload = format!(
                "{{\"version\":\"{}\",\"colors\":[{}]}}",
                VERSION,
                colors
                    .iter()
                    .map(|c| format!("[{},{},{}]", c.r, c.g, c.b))
                    .collect::<Vec<_>>()
                    .join(",")
            );
            string_to_ptr(payload)
        }
        Err(err) => string_to_ptr(format!("{{\"error\":\"{}\"}}", escape_json(&err))),
    }
}

fn extract_colors_internal(
    data_ptr: *const u8,
    data_len: usize,
    num_colors: i32,
    min_distance: f32,
    max_image_size: i32,
) -> Result<Vec<Rgb>, String> {
    if data_ptr.is_null() || data_len < 8 {
        return Err("图像数据为空或格式无效".to_string());
    }

    let bytes = unsafe { slice::from_raw_parts(data_ptr, data_len) };
    let width = i32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]);
    let height = i32::from_le_bytes([bytes[4], bytes[5], bytes[6], bytes[7]]);

    if width <= 0 || height <= 0 {
        return Err("图像尺寸无效".to_string());
    }

    let pixel_data = &bytes[8..];
    let pixel_count = (width as usize) * (height as usize);
    if pixel_count == 0 {
        return Err("像素数量无效".to_string());
    }

    let channels = pixel_data.len() / pixel_count;
    if channels != 3 && channels != 4 {
        return Err("不支持的图像格式（需要 RGB 或 RGBA）".to_string());
    }

    let target_w = width.min(max_image_size.max(1)) as usize;
    let target_h = height.min(max_image_size.max(1)) as usize;

    let mut sampled = Vec::with_capacity(target_w * target_h);

    for y in 0..target_h {
        for x in 0..target_w {
            let src_x = x * width as usize / target_w;
            let src_y = y * height as usize / target_h;
            let idx = (src_y * width as usize + src_x) * channels;

            let r = pixel_data[idx];
            let g = pixel_data[idx + 1];
            let b = pixel_data[idx + 2];

            if channels == 4 {
                let a = pixel_data[idx + 3];
                if a < 128 {
                    continue;
                }
            }

            let brightness = (r as i32 + g as i32 + b as i32) / 3;
            if !(12..=245).contains(&brightness) {
                continue;
            }

            sampled.push(Rgb { r, g, b });
        }
    }

    if sampled.len() < 10 {
        return Err("有效像素数量不足".to_string());
    }

    downsample_deterministic(&mut sampled, 6000);

    let lab_pixels: Vec<Lab> = sampled.into_iter().map(rgb_to_lab).collect();
    let mut clusters = kmeans_lab(&lab_pixels, 8, 24);

    clusters.sort_by(|a, b| b.size.cmp(&a.size));

    let desired = num_colors.max(1) as usize;
    let mut selected: Vec<Lab> = Vec::with_capacity(desired);

    for cluster in &clusters {
        if selected.len() >= desired.min(6) {
            break;
        }
        if selected
            .iter()
            .all(|chosen| ciede2000(cluster.centroid, *chosen) >= min_distance.max(18.0))
        {
            selected.push(cluster.centroid);
        }
    }

    if selected.len() < 4 {
        for cluster in &clusters {
            if selected.len() >= desired.min(6) {
                break;
            }
            let duplicate = selected
                .iter()
                .any(|chosen| ciede2000(cluster.centroid, *chosen) < 1.0);
            if !duplicate {
                selected.push(cluster.centroid);
            }
        }
    }

    if selected.is_empty() {
        return Err("未能提取有效聚类颜色".to_string());
    }

    let palette = build_visual_palette(&selected, desired.max(5));
    Ok(palette)
}

fn build_visual_palette(labs: &[Lab], desired: usize) -> Vec<Rgb> {
    let mut prepared: Vec<Rgb> = labs
        .iter()
        .map(|lab| enhance_background_color(lab_to_rgb(*lab), 1.0))
        .collect();

    prepared.sort_by(|a, b| score_rgb(*b).partial_cmp(&score_rgb(*a)).unwrap_or(Ordering::Equal));

    let primary = prepared[0];
    let mut accents = Vec::new();

    for color in prepared.iter().skip(1) {
        if accents.len() >= 2 {
            break;
        }
        let (h1, s1, v1) = rgb_to_hsv(primary);
        let (h2, s2, v2) = rgb_to_hsv(*color);
        let hue_gap = hue_distance(h1, h2);
        let sat_gap = (s1 - s2).abs();
        let val_gap = (v1 - v2).abs();

        if hue_gap >= 22.0 || sat_gap >= 0.11 || val_gap >= 0.10 {
            accents.push(enhance_background_color(*color, 1.08));
        }
    }

    if accents.len() < 2 {
        accents.push(shift_rgb(primary, 22.0, 1.10, 1.05));
    }
    if accents.len() < 2 {
        accents.push(shift_rgb(primary, -26.0, 1.06, 0.98));
    }

    let light_variant = shift_rgb(primary, 8.0, 0.92, 1.23);
    let dark_variant = shift_rgb(primary, -10.0, 1.08, 0.72);

    let mut palette = vec![primary, accents[0], accents[1], light_variant, dark_variant];

    while palette.len() < desired {
        let source = palette[palette.len() % 5];
        let extra = shift_rgb(source, 12.0 * palette.len() as f32, 0.96, 0.92);
        palette.push(extra);
    }

    palette.truncate(desired);
    palette
}

fn score_rgb(rgb: Rgb) -> f32 {
    let (_, s, v) = rgb_to_hsv(rgb);
    s * 0.7 + (1.0 - (v - 0.58).abs()) * 0.3
}

fn enhance_background_color(rgb: Rgb, sat_mul: f32) -> Rgb {
    let (mut h, mut s, mut v) = rgb_to_hsv(rgb);
    if h.is_nan() {
        h = 280.0;
    }
    s = (s * 1.18 * sat_mul).clamp(0.31, 0.92);
    v = (v * 1.05).clamp(0.31, 0.86);
    hsv_to_rgb(h, s, v)
}

fn shift_rgb(rgb: Rgb, hue_shift: f32, sat_mul: f32, val_mul: f32) -> Rgb {
    let (mut h, mut s, mut v) = rgb_to_hsv(rgb);
    if h.is_nan() {
        h = 280.0;
    }
    h = (h + hue_shift).rem_euclid(360.0);
    s = (s * sat_mul).clamp(0.25, 1.0);
    v = (v * val_mul).clamp(0.16, 1.0);
    hsv_to_rgb(h, s, v)
}

fn hue_distance(h1: f32, h2: f32) -> f32 {
    let diff = (h1 - h2).abs().rem_euclid(360.0);
    diff.min(360.0 - diff)
}

fn rgb_to_hsv(rgb: Rgb) -> (f32, f32, f32) {
    let r = rgb.r as f32 / 255.0;
    let g = rgb.g as f32 / 255.0;
    let b = rgb.b as f32 / 255.0;

    let max = r.max(g).max(b);
    let min = r.min(g).min(b);
    let delta = max - min;

    let h = if delta == 0.0 {
        f32::NAN
    } else if max == r {
        60.0 * (((g - b) / delta).rem_euclid(6.0))
    } else if max == g {
        60.0 * (((b - r) / delta) + 2.0)
    } else {
        60.0 * (((r - g) / delta) + 4.0)
    };

    let s = if max == 0.0 { 0.0 } else { delta / max };
    let v = max;
    (h, s, v)
}

fn hsv_to_rgb(h: f32, s: f32, v: f32) -> Rgb {
    let c = v * s;
    let x = c * (1.0 - (((h / 60.0).rem_euclid(2.0)) - 1.0).abs());
    let m = v - c;

    let (r1, g1, b1) = if h < 60.0 {
        (c, x, 0.0)
    } else if h < 120.0 {
        (x, c, 0.0)
    } else if h < 180.0 {
        (0.0, c, x)
    } else if h < 240.0 {
        (0.0, x, c)
    } else if h < 300.0 {
        (x, 0.0, c)
    } else {
        (c, 0.0, x)
    };

    Rgb {
        r: ((r1 + m).clamp(0.0, 1.0) * 255.0).round() as u8,
        g: ((g1 + m).clamp(0.0, 1.0) * 255.0).round() as u8,
        b: ((b1 + m).clamp(0.0, 1.0) * 255.0).round() as u8,
    }
}

fn downsample_deterministic(data: &mut Vec<Rgb>, limit: usize) {
    if data.len() <= limit {
        return;
    }

    let step = data.len() as f32 / limit as f32;
    let mut out = Vec::with_capacity(limit);
    let mut index = 0.0_f32;
    while out.len() < limit {
        let i = index.floor() as usize;
        out.push(data[i.min(data.len() - 1)]);
        index += step;
    }
    *data = out;
}

fn kmeans_lab(pixels: &[Lab], k: usize, max_iters: usize) -> Vec<Cluster> {
    if pixels.is_empty() || k == 0 {
        return Vec::new();
    }

    let mut centroids = Vec::with_capacity(k);
    let stride = (pixels.len() / k.max(1)).max(1);
    for i in 0..k {
        let idx = (i * stride).min(pixels.len() - 1);
        centroids.push(pixels[idx]);
    }

    let mut assignments = vec![0usize; pixels.len()];
    let mut cluster_sizes = vec![0usize; k];

    for _ in 0..max_iters {
        for (i, pixel) in pixels.iter().enumerate() {
            let mut min_dist = f32::MAX;
            let mut closest = 0usize;

            for (j, centroid) in centroids.iter().enumerate() {
                let dist = ciede2000(*pixel, *centroid);
                if dist < min_dist {
                    min_dist = dist;
                    closest = j;
                }
            }
            assignments[i] = closest;
        }

        let mut new_centroids = vec![Lab { l: 0.0, a: 0.0, b: 0.0 }; k];
        cluster_sizes.fill(0);

        for (pixel, cluster) in pixels.iter().zip(assignments.iter()) {
            new_centroids[*cluster].l += pixel.l;
            new_centroids[*cluster].a += pixel.a;
            new_centroids[*cluster].b += pixel.b;
            cluster_sizes[*cluster] += 1;
        }

        for i in 0..k {
            if cluster_sizes[i] > 0 {
                let inv = 1.0 / cluster_sizes[i] as f32;
                new_centroids[i].l *= inv;
                new_centroids[i].a *= inv;
                new_centroids[i].b *= inv;
            } else {
                new_centroids[i] = pixels[(i * 997 + 17) % pixels.len()];
            }
        }

        let converged = centroids
            .iter()
            .zip(new_centroids.iter())
            .all(|(old, new)| ciede2000(*old, *new) <= 1.0);

        centroids = new_centroids;

        if converged {
            break;
        }
    }

    centroids
        .into_iter()
        .enumerate()
        .map(|(i, centroid)| Cluster {
            centroid,
            size: cluster_sizes[i],
        })
        .collect()
}

fn gamma_correct(c: f32) -> f32 {
    if c > 0.04045 {
        ((c + 0.055) / 1.055).powf(2.4)
    } else {
        c / 12.92
    }
}

fn gamma_uncorrect(c: f32) -> f32 {
    if c > 0.0031308 {
        1.055 * c.powf(1.0 / 2.4) - 0.055
    } else {
        12.92 * c
    }
}

fn rgb_to_lab(rgb: Rgb) -> Lab {
    let mut r = rgb.r as f32 / 255.0;
    let mut g = rgb.g as f32 / 255.0;
    let mut b = rgb.b as f32 / 255.0;

    r = gamma_correct(r);
    g = gamma_correct(g);
    b = gamma_correct(b);

    let mut x = r * 0.4124 + g * 0.3576 + b * 0.1805;
    let mut y = r * 0.2126 + g * 0.7152 + b * 0.0722;
    let mut z = r * 0.0193 + g * 0.1192 + b * 0.9505;

    x /= 0.95047;
    y /= 1.0;
    z /= 1.08883;

    let f = |t: f32| {
        if t > 0.008856 {
            t.cbrt()
        } else {
            7.787 * t + 16.0 / 116.0
        }
    };

    let fx = f(x);
    let fy = f(y);
    let fz = f(z);

    Lab {
        l: 116.0 * fy - 16.0,
        a: 500.0 * (fx - fy),
        b: 200.0 * (fy - fz),
    }
}

fn lab_to_rgb(lab: Lab) -> Rgb {
    let fy = (lab.l + 16.0) / 116.0;
    let fx = lab.a / 500.0 + fy;
    let fz = fy - lab.b / 200.0;

    let finv = |t: f32| {
        let t3 = t * t * t;
        if t3 > 0.008856 {
            t3
        } else {
            (t - 16.0 / 116.0) / 7.787
        }
    };

    let x = finv(fx) * 0.95047;
    let y = finv(fy) * 1.0;
    let z = finv(fz) * 1.08883;

    let mut r = x * 3.2406 + y * -1.5372 + z * -0.4986;
    let mut g = x * -0.9689 + y * 1.8758 + z * 0.0415;
    let mut b = x * 0.0557 + y * -0.2040 + z * 1.0570;

    r = gamma_uncorrect(r).clamp(0.0, 1.0);
    g = gamma_uncorrect(g).clamp(0.0, 1.0);
    b = gamma_uncorrect(b).clamp(0.0, 1.0);

    Rgb {
        r: (r * 255.0).round() as u8,
        g: (g * 255.0).round() as u8,
        b: (b * 255.0).round() as u8,
    }
}

fn ciede2000(lab1: Lab, lab2: Lab) -> f32 {
    let (l1, a1, b1) = (lab1.l, lab1.a, lab1.b);
    let (l2, a2, b2) = (lab2.l, lab2.a, lab2.b);

    let c1 = (a1 * a1 + b1 * b1).sqrt();
    let c2 = (a2 * a2 + b2 * b2).sqrt();
    let c_avg = (c1 + c2) / 2.0;

    let g = 0.5 * (1.0 - ((c_avg.powi(7)) / (c_avg.powi(7) + 25.0_f32.powi(7))).sqrt());
    let a1p = a1 * (1.0 + g);
    let a2p = a2 * (1.0 + g);

    let c1p = (a1p * a1p + b1 * b1).sqrt();
    let c2p = (a2p * a2p + b2 * b2).sqrt();

    let h1p = atan2_deg(b1, a1p);
    let h2p = atan2_deg(b2, a2p);

    let dl = l2 - l1;
    let dc = c2p - c1p;

    let dh = if c1p * c2p == 0.0 {
        0.0
    } else {
        let diff = h2p - h1p;
        if diff.abs() <= 180.0 {
            diff
        } else if diff > 180.0 {
            diff - 360.0
        } else {
            diff + 360.0
        }
    };

    let d_h = 2.0 * (c1p * c2p).sqrt() * (dh.to_radians() / 2.0).sin();

    let l_avg = (l1 + l2) / 2.0;
    let c_avg_p = (c1p + c2p) / 2.0;

    let h_avg_p = if c1p * c2p == 0.0 {
        h1p + h2p
    } else {
        let sum = h1p + h2p;
        let diff = (h1p - h2p).abs();
        if diff <= 180.0 {
            sum / 2.0
        } else if sum < 360.0 {
            (sum + 360.0) / 2.0
        } else {
            (sum - 360.0) / 2.0
        }
    };

    let t = 1.0
        - 0.17 * (h_avg_p - 30.0).to_radians().cos()
        + 0.24 * (2.0 * h_avg_p).to_radians().cos()
        + 0.32 * (3.0 * h_avg_p + 6.0).to_radians().cos()
        - 0.20 * (4.0 * h_avg_p - 63.0).to_radians().cos();

    let delta_theta = 30.0 * (-(((h_avg_p - 275.0) / 25.0).powi(2))).exp();
    let r_c = 2.0 * ((c_avg_p.powi(7)) / (c_avg_p.powi(7) + 25.0_f32.powi(7))).sqrt();

    let s_l = 1.0 + (0.015 * (l_avg - 50.0).powi(2)) / (20.0 + (l_avg - 50.0).powi(2)).sqrt();
    let s_c = 1.0 + 0.045 * c_avg_p;
    let s_h = 1.0 + 0.015 * c_avg_p * t;
    let r_t = -(2.0 * delta_theta).to_radians().sin() * r_c;

    let dl_term = dl / s_l;
    let dc_term = dc / s_c;
    let dh_term = d_h / s_h;

    (dl_term * dl_term + dc_term * dc_term + dh_term * dh_term + r_t * dc_term * dh_term).sqrt()
}

fn atan2_deg(y: f32, x: f32) -> f32 {
    let mut deg = y.atan2(x).to_degrees();
    if deg < 0.0 {
        deg += 360.0;
    }
    deg
}

fn string_to_ptr(text: String) -> *mut c_char {
    CString::new(text).unwrap().into_raw()
}

fn escape_json(input: &str) -> String {
    input.replace('\\', "\\\\").replace('"', "\\\"")
}
