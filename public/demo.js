const presets = {
  public: {
    method: "GET",
    path: "/public/file1.html",
    headers: "Accept: text/html",
  },
  head: {
    method: "HEAD",
    path: "/public/file1.html",
    headers: "Accept: text/html",
  },
  private403: {
    method: "GET",
    path: "/private/file2.html",
    headers: "Accept: text/html",
  },
  private200: {
    method: "GET",
    path: "/private/file2.html",
    headers: "Accept: text/html\nAuthorization: Basic dXNlcm5hbWU6cGFzc3dvcmQ=",
  },
  notModified: {
    method: "GET",
    path: "/public/file1.html",
    headers: "Accept: text/html\nIf-Modified-Since: Sun, 27 Apr 3000 10:00:00 GMT",
  },
  unsupported: {
    method: "POST",
    path: "/public/file1.html",
    headers: "Accept: text/html",
  },
};

const form = document.querySelector("#requestForm");
const methodInput = document.querySelector("#method");
const pathInput = document.querySelector("#path");
const headersInput = document.querySelector("#headers");
const statusCode = document.querySelector("#statusCode");
const methodEcho = document.querySelector("#methodEcho");
const duration = document.querySelector("#duration");
const requestPreview = document.querySelector("#requestPreview");
const responseHeaders = document.querySelector("#responseHeaders");
const responseBody = document.querySelector("#responseBody");
const serverOrigin = document.querySelector("#serverOrigin");

serverOrigin.textContent = window.location.host;

function parseHeaders(rawHeaders) {
  const headers = new Headers();
  const previewLines = [];

  rawHeaders
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .forEach((line) => {
      const separator = line.indexOf(":");
      if (separator === -1) {
        throw new Error(`Invalid header: ${line}`);
      }
      const name = line.slice(0, separator).trim();
      const value = line.slice(separator + 1).trim();
      headers.set(name, value);
      previewLines.push(`${name}: ${value}`);
    });

  return { headers, previewLines };
}

function renderRequest(method, path, previewLines) {
  requestPreview.textContent = [`${method} ${path} HTTP/1.1`, ...previewLines].join("\n");
}

function renderHeaders(headers) {
  const lines = [];
  headers.forEach((value, name) => {
    lines.push(`${name}: ${value}`);
  });
  responseHeaders.textContent = lines.length ? lines.join("\n") : "No response headers.";
}

function setStatus(status, statusText) {
  const label = status ? `${status} ${statusText}`.trim() : "Error";
  statusCode.textContent = label;
  statusCode.classList.toggle("status-ok", status >= 200 && status < 400);
  statusCode.classList.toggle("status-error", !status || status >= 400);
}

async function sendRequest(event) {
  event.preventDefault();

  const method = methodInput.value.trim().toUpperCase();
  const path = pathInput.value.trim() || "/";
  let parsed;

  try {
    parsed = parseHeaders(headersInput.value);
  } catch (error) {
    setStatus(0, "");
    methodEcho.textContent = method;
    duration.textContent = "0 ms";
    requestPreview.textContent = `${method} ${path} HTTP/1.1`;
    responseHeaders.textContent = error.message;
    responseBody.textContent = "";
    return;
  }

  renderRequest(method, path, parsed.previewLines);
  methodEcho.textContent = method;
  duration.textContent = "Pending";
  responseHeaders.textContent = "Waiting for response...";
  responseBody.textContent = "";

  const startedAt = performance.now();
  try {
    const response = await fetch(path, {
      method,
      headers: parsed.headers,
      cache: "no-store",
    });
    const elapsed = Math.round(performance.now() - startedAt);
    const body = method === "HEAD" ? "" : await response.text();

    setStatus(response.status, response.statusText);
    duration.textContent = `${elapsed} ms`;
    renderHeaders(response.headers);
    responseBody.textContent = body || "(empty body)";
  } catch (error) {
    const elapsed = Math.round(performance.now() - startedAt);
    setStatus(0, "");
    duration.textContent = `${elapsed} ms`;
    responseHeaders.textContent = error.message;
    responseBody.textContent = "";
  }
}

document.querySelectorAll("[data-preset]").forEach((button) => {
  button.addEventListener("click", () => {
    const preset = presets[button.dataset.preset];
    methodInput.value = preset.method;
    pathInput.value = preset.path;
    headersInput.value = preset.headers;
    renderRequest(preset.method, preset.path, preset.headers.split(/\r?\n/).filter(Boolean));
  });
});

form.addEventListener("submit", sendRequest);
