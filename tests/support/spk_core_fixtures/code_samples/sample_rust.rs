// Parity sample: rust — COMMENT line
const LIMIT: u32 = 100; // NUMBER 100

fn classify(n: u32) -> &'static str { // keyword: fn
    // COMMENT branch
    if n > LIMIT { // keyword: if
        "too big" // STRING
    } else {
        "ok" // STRING
    }
}

fn main() {
    println!("{}", classify(7)); // NUMBER 7
}
