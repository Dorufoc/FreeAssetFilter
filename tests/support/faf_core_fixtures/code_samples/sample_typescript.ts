// Parity sample: typescript — COMMENT line
const TIMEOUT_MS: number = 1500; // NUMBER 1500

interface Config { // keyword: interface
  endpoint: string; // STRING type
  retries: number;
}

function buildUrl(cfg: Config): string { // keyword: function, return STRING
  return `https://${cfg.endpoint}?r=${cfg.retries}`;
}

export { buildUrl };
