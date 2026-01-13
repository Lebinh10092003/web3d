function parseScratchblocksTextFromScriptId(scriptId) {
  const script = document.getElementById(scriptId);
  if (!script) {
    return "";
  }
  const raw = script.textContent || "";
  try {
    const decoded = JSON.parse(raw || "null");
    if (decoded == null) {
      return "";
    }
    if (typeof decoded === "string") {
      return decoded.replace("\r\n", "\n").trim();
    }
    return String(decoded).replace("\r\n", "\n").trim();
  } catch (error) {
    return String(raw).replace("\r\n", "\n").trim();
  }
}

function getScratchblocksLanguages() {
  const raw = String(document.documentElement?.getAttribute("lang") || "")
    .trim()
    .toLowerCase();
  const primary = raw.split("-")[0] || "en";
  const languages = ["en"];
  if (primary && primary !== "en") {
    languages.push(primary);
  }
  return languages;
}

function initScratchblocksPreviewElement(element) {
  if (!element || element.dataset.scratchInit === "1") {
    return;
  }
  const scriptId = element.dataset.scratchblocksScriptId;
  if (!scriptId) {
    return;
  }
  const text = parseScratchblocksTextFromScriptId(scriptId);
  if (!text) {
    return;
  }

  element.dataset.scratchInit = "1";
  element.innerHTML = "";

  const pre = document.createElement("pre");
  pre.className = "scratchblocks";
  pre.id = `scratchblocks-${Math.random().toString(36).slice(2)}`;
  pre.textContent = text;
  element.appendChild(pre);

  const scratchblocks = window.scratchblocks;
  if (!scratchblocks) {
    element.dataset.scratchInit = "missing";
    element.insertAdjacentHTML(
      "beforeend",
      '<div class="text-muted small mt-2">Scratch blocks renderer is not loaded.</div>'
    );
    return;
  }

  const languages = getScratchblocksLanguages();
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
    element.dataset.scratchInit = "error";
  }
}

function initScratchblocksPreviews(root) {
  const container = root || document;
  const previews = container.querySelectorAll("[data-scratchblocks-preview]");
  previews.forEach(initScratchblocksPreviewElement);
}

document.addEventListener("DOMContentLoaded", () => {
  initScratchblocksPreviews(document);
});

document.addEventListener("htmx:afterSwap", (event) => {
  initScratchblocksPreviews(event.target);
});

window.ScratchblocksQuiz = window.ScratchblocksQuiz || {};
window.ScratchblocksQuiz.initPreviews = initScratchblocksPreviews;
