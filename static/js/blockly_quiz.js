function parseBlocklyPreviewPayloadFromScriptId(scriptId) {
  const script = document.getElementById(scriptId);
  if (!script) {
    return null;
  }
  try {
    const decoded = JSON.parse(script.textContent || "null");
    if (decoded == null) {
      return null;
    }

    if (typeof decoded === "string") {
      const trimmed = decoded.trim();
      if (!trimmed) {
        return null;
      }
      if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
        try {
          return { kind: "state", value: JSON.parse(trimmed) };
        } catch (error) {
          return { kind: "xml", value: trimmed };
        }
      }
      if (trimmed.startsWith("<")) {
        return { kind: "xml", value: trimmed };
      }
      return { kind: "xml", value: trimmed };
    }

    if (typeof decoded === "object") {
      return { kind: "state", value: decoded };
    }

    return null;
  } catch (error) {
    return null;
  }
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = String(text ?? "");
  return div.innerHTML;
}

function getBlocklyQuizI18nString(key, fallback) {
  const i18n = window.BLOCKLY_QUIZ_I18N;
  const value = i18n && typeof i18n === "object" ? i18n[key] : null;
  if (typeof value === "string" && value.length) {
    return value;
  }
  return fallback;
}

function showPreviewError(element, title, message) {
  if (!element) {
    return;
  }
  const safeTitle = escapeHtml(
    title || getBlocklyQuizI18nString("previewError", "Preview error")
  );
  const safeMessage = escapeHtml(message || "");
  element.innerHTML = `
    <div class="alert alert-warning mb-0">
      <div class="fw-semibold">${safeTitle}</div>
      ${safeMessage ? `<div class="small mt-1">${safeMessage}</div>` : ""}
    </div>
  `;
}

function parseBlocklyXmlText(xmlText) {
  const text = String(xmlText || "").trim();
  if (!text) {
    throw new Error(getBlocklyQuizI18nString("blocklyXmlEmpty", "Blockly XML is empty."));
  }

  const blockly = window.Blockly;
  if (!blockly) {
    throw new Error(getBlocklyQuizI18nString("blocklyIsNotLoaded", "Blockly is not loaded."));
  }

  if (blockly.Xml && typeof blockly.Xml.textToDom === "function") {
    return blockly.Xml.textToDom(text);
  }

  const utilsXml = blockly.utils && blockly.utils.xml;
  if (utilsXml && typeof utilsXml.textToDom === "function") {
    return utilsXml.textToDom(text);
  }

  if (typeof DOMParser !== "undefined") {
    const parser = new DOMParser();
    const doc = parser.parseFromString(text, "text/xml");
    const parserError = doc.querySelector("parsererror");
    if (parserError) {
      throw new Error(getBlocklyQuizI18nString("invalidBlocklyXml", "Invalid Blockly XML."));
    }
    return doc.documentElement || doc;
  }

  throw new Error(
    getBlocklyQuizI18nString(
      "blocklyXmlParserUnavailable",
      "Blockly XML parser is not available in this Blockly build."
    )
  );
}

function loadBlocklyXmlIntoWorkspace(xmlDom, workspace) {
  const blockly = window.Blockly;
  if (!blockly || !blockly.Xml) {
    throw new Error(
      getBlocklyQuizI18nString(
        "blocklyXmlUnavailable",
        "Blockly.Xml is not available in this Blockly build."
      )
    );
  }

  const dom =
    xmlDom && xmlDom.nodeType === 9
      ? xmlDom.documentElement
      : xmlDom && xmlDom.nodeType
        ? xmlDom
        : null;

  if (!dom) {
    throw new Error(
      getBlocklyQuizI18nString("invalidBlocklyXmlDom", "Invalid Blockly XML DOM.")
    );
  }

  if (typeof blockly.Xml.domToWorkspace === "function") {
    blockly.Xml.domToWorkspace(dom, workspace);
    return;
  }

  if (typeof blockly.Xml.clearWorkspaceAndLoadFromXml === "function") {
    blockly.Xml.clearWorkspaceAndLoadFromXml(dom, workspace);
    return;
  }

  throw new Error(
    getBlocklyQuizI18nString(
      "blocklyXmlLoaderUnavailable",
      "Blockly XML loader is not available in this Blockly build."
    )
  );
}

function initBlocklyPreviewElement(element) {
  if (!element || element.dataset.blocklyInit === "1") {
    return;
  }
  const scriptId = element.dataset.blocklyScriptId;
  if (!scriptId) {
    return;
  }
  const payload = parseBlocklyPreviewPayloadFromScriptId(scriptId);
  if (!payload) {
    return;
  }

  if (!window.Blockly) {
    element.dataset.blocklyInit = "missing";
    showPreviewError(
      element,
      getBlocklyQuizI18nString("blocklyNotLoadedTitle", "Blockly library is not loaded."),
      getBlocklyQuizI18nString(
        "blocklyNotLoadedHint",
        "Check BLOCKLY_QUIZ_BLOCKLY_JS_URLS / BLOCKLY_QUIZ_BLOCKLY_JS_URL."
      )
    );
    return;
  }

  try {
    if (
      !window.Blockly.__quizLocaleApplied &&
      typeof window.Blockly.setLocale === "function" &&
      window.Blockly.Msg
    ) {
      window.Blockly.setLocale(window.Blockly.Msg);
      window.Blockly.__quizLocaleApplied = true;
    }
  } catch (error) {
    // ignore locale issues
  }

  element.dataset.blocklyInit = "1";
  element.innerHTML = "";

  const options = {
    readOnly: true,
    scrollbars: true,
    trashcan: false,
    zoom: {
      controls: true,
      wheel: true,
      startScale: 0.9,
      maxScale: 1.2,
      minScale: 0.4,
      scaleSpeed: 1.1
    }
  };

  const mediaUrl = String(window.BLOCKLY_QUIZ_MEDIA_URL || "").trim();
  if (mediaUrl) {
    options.media = mediaUrl;
  }

  const workspace = window.Blockly.inject(element, options);

  try {
    const canLoadState =
      window.Blockly.serialization &&
      window.Blockly.serialization.workspaces &&
      typeof window.Blockly.serialization.workspaces.load === "function";
    if (payload.kind === "state") {
      if (!canLoadState) {
        throw new Error(
          getBlocklyQuizI18nString(
            "missingSerialization",
            "Missing Blockly.serialization. Load a newer build (e.g. blockly.min.js) or use blockly_xml instead of blockly_state."
          )
        );
      }
      window.Blockly.serialization.workspaces.load(payload.value, workspace);
    } else {
      const dom = parseBlocklyXmlText(payload.value);
      loadBlocklyXmlIntoWorkspace(dom, workspace);
    }
    workspace.scrollCenter();
  } catch (error) {
    element.dataset.blocklyInit = "error";
    try {
      workspace.dispose();
    } catch (disposeError) {
      // ignore
    }
    const hint = getBlocklyQuizI18nString(
      "blocklyRenderHint",
      "Usually caused by missing block types/custom blocks; load the same JS block definitions as the editor."
    );
    const errorMessage = `${(error && error.message) || String(error || "")}`;
    showPreviewError(
      element,
      getBlocklyQuizI18nString("blocklyRenderFailedTitle", "Could not render Blockly blocks."),
      hint ? `${errorMessage} (${hint})` : errorMessage
    );
    return;
  }

  element._blocklyWorkspace = workspace;
  window.Blockly.svgResize(workspace);
}

function initBlocklyPreviews(root) {
  const container = root || document;
  const previews = container.querySelectorAll("[data-blockly-preview]");
  previews.forEach(initBlocklyPreviewElement);
}

document.addEventListener("DOMContentLoaded", () => {
  initBlocklyPreviews(document);
});

document.addEventListener("htmx:afterSwap", (event) => {
  initBlocklyPreviews(event.target);
});

window.addEventListener("resize", () => {
  const previews = document.querySelectorAll("[data-blockly-preview]");
  previews.forEach((element) => {
    const workspace = element._blocklyWorkspace;
    if (workspace && window.Blockly) {
      window.Blockly.svgResize(workspace);
    }
  });
});

window.BlocklyQuiz = window.BlocklyQuiz || {};
window.BlocklyQuiz.initPreviews = initBlocklyPreviews;

function syncChoiceListSelection(choiceList) {
  if (!choiceList) {
    return;
  }
  const labels = choiceList.querySelectorAll("label.list-group-item");
  labels.forEach((label) => {
    const input = label.querySelector("input[name='choice_id']");
    label.classList.toggle("is-selected", Boolean(input && input.checked));
  });
}

function syncChoiceSelection(root) {
  const container = root || document;
  if (!container || typeof container.querySelectorAll !== "function") {
    return;
  }
  container.querySelectorAll(".quiz-choice-list").forEach(syncChoiceListSelection);
}

document.addEventListener("change", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement)) {
    return;
  }
  if (target.name !== "choice_id") {
    return;
  }
  const choiceList = target.closest(".quiz-choice-list");
  if (!choiceList) {
    return;
  }
  syncChoiceListSelection(choiceList);
});

document.addEventListener("DOMContentLoaded", () => {
  syncChoiceSelection(document);
});

document.addEventListener("htmx:afterSwap", (event) => {
  const target =
    event && event.detail && event.detail.target && event.detail.target.querySelectorAll
      ? event.detail.target
      : event.target;
  syncChoiceSelection(target);
});
