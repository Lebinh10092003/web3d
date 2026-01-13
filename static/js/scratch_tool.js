function showToast(message, icon) {
  if (!window.Swal) {
    return;
  }
  window.Swal.fire({
    toast: true,
    position: "top-end",
    showConfirmButton: false,
    timer: 2500,
    timerProgressBar: true,
    icon: icon || "info",
    title: message || ""
  });
}

function copyToClipboard(text) {
  if (!navigator.clipboard) {
    return Promise.reject(new Error("Clipboard API not available"));
  }
  return navigator.clipboard.writeText(text);
}

function renderScratchblocksInto(container, rawText) {
  if (!container) {
    return;
  }
  const text = String(rawText || "").replace("\r\n", "\n").trim();
  container.innerHTML = "";

  if (!text) {
    container.innerHTML = '<div class="text-muted">No blocks.</div>';
    return;
  }

  const pre = document.createElement("pre");
  pre.className = "scratchblocks";
  pre.id = `scratchblocks-tool-${Math.random().toString(36).slice(2)}`;
  pre.textContent = text;
  container.appendChild(pre);

  const scratchblocks = window.scratchblocks;
  if (!scratchblocks) {
    showToast("scratchblocks library not loaded.", "warning");
    return;
  }

  const rawLang = String(document.documentElement?.getAttribute("lang") || "")
    .trim()
    .toLowerCase();
  const primaryLang = rawLang.split("-")[0] || "en";
  const languages = ["en"];
  if (primaryLang && primaryLang !== "en") {
    languages.push(primaryLang);
  }

  try {
    if (typeof scratchblocks.renderMatching === "function") {
      scratchblocks.renderMatching(`#${pre.id}`, {
        style: "scratch3",
        languages
      });
      return;
    }
    if (typeof scratchblocks.render === "function") {
      scratchblocks.render(`#${pre.id}`, { style: "scratch3", languages });
    }
  } catch (error) {
    showToast(`Render failed: ${error?.message || error}`, "error");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const root = document.querySelector("[data-scratch-tool]");
  if (!root) {
    return;
  }

  const input = root.querySelector("#scratchblocks-input");
  const preview = root.querySelector("#scratchblocks-preview");
  if (!input || !preview) {
    return;
  }

  const sample = `when green flag clicked
set [score v] to (0)
repeat (5)
  change [score v] by (1)
end
say (score) for (2) secs`;

  const render = () => renderScratchblocksInto(preview, input.value);

  let debounce = 0;
  input.addEventListener("input", () => {
    window.clearTimeout(debounce);
    debounce = window.setTimeout(render, 250);
  });

  root.querySelector("[data-scratch-render]")?.addEventListener("click", render);

  root.querySelector("[data-scratch-clear]")?.addEventListener("click", () => {
    input.value = "";
    render();
    showToast("Cleared.", "success");
  });

  root.querySelector("[data-scratch-sample]")?.addEventListener("click", () => {
    input.value = sample;
    render();
    showToast("Loaded sample.", "success");
  });

  root.querySelector("[data-scratch-copy]")?.addEventListener("click", () => {
    const text = (input.value || "").trim();
    if (!text) {
      showToast("Nothing to copy.", "warning");
      return;
    }
    copyToClipboard(text)
      .then(() => showToast("Copied.", "success"))
      .catch(() => showToast("Copy failed.", "error"));
  });

  input.value = sample;
  render();
});
