// Parity sample: javascript — COMMENT line
const MAX_RETRY = 3; // NUMBER 3

function fetchData(url) { // keyword: function
  const label = "loading"; // STRING
  for (let i = 0; i < MAX_RETRY; i++) { // keyword: for, NUMBER 0
    console.log(`${label}: ${url}`);
  }
  return null;
}

module.exports = { fetchData };
