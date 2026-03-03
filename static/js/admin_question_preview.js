(function () {
  window.__adminQuestionPreviewVersion = "2026-03-03-compat-v1";

  function getValue(field) {
    if (!field || typeof field.value !== "string") {
      return "";
    }
    return field.value.replace(/\r\n/g, "\n").trim();
  }

  function getRawValue(field) {
    if (!field || typeof field.value !== "string") {
      return "";
    }
    return field.value.replace(/\r\n/g, "\n");
  }

  function setVisible(element, visible) {
    if (!element) {
      return;
    }
    element.hidden = !visible;
  }

  function setText(element, text) {
    if (!element) {
      return;
    }
    element.textContent = text || "";
  }

  function pickFirst(root, selectors) {
    for (const selector of selectors) {
      const node = root.querySelector(selector);
      if (node) {
        return node;
      }
    }
    return null;
  }

  function normalizeQuestionType(value) {
    const normalized = String(value || "").trim().toLowerCase();
    if (normalized === "blockly" || normalized === "scratch" || normalized === "code") {
      return normalized;
    }
    return "";
  }

  function disposeBlockly(surface) {
    if (!surface) {
      return;
    }
    const workspace = surface._blocklyWorkspace;
    if (workspace && typeof workspace.dispose === "function") {
      try {
        workspace.dispose();
      } catch (error) {
        // ignore cleanup failure
      }
    }
    surface._blocklyWorkspace = null;
    surface.innerHTML = "";
  }

  function parseBlocklyStatePayload(stateText) {
    if (!stateText) {
      return { payload: null, error: "", label: "" };
    }
    try {
      const parsed = JSON.parse(stateText);
      if (parsed && typeof parsed === "object") {
        return { payload: { kind: "state", value: parsed }, error: "", label: "Blockly JSON" };
      }
      if (typeof parsed === "string") {
        const inner = parsed.trim();
        if (!inner) {
          return { payload: null, error: "blockly_state JSON is empty.", label: "" };
        }
        if (inner.startsWith("<")) {
          return {
            payload: { kind: "xml", value: inner },
            error: "",
            label: "Blockly XML (from blockly_state)"
          };
        }
        try {
          const nested = JSON.parse(inner);
          if (nested && typeof nested === "object") {
            return {
              payload: { kind: "state", value: nested },
              error: "",
              label: "Blockly JSON (nested)"
            };
          }
        } catch (nestedError) {
          // fall through to validation error
        }
      }
      return {
        payload: null,
        error: "blockly_state must be a JSON object (workspace state).",
        label: ""
      };
    } catch (error) {
      return { payload: null, error: "blockly_state JSON is invalid.", label: "" };
    }
  }

  function parseBlocklyXmlPayload(xmlText) {
    if (!xmlText) {
      return { payload: null, error: "", label: "" };
    }
    return { payload: { kind: "xml", value: xmlText }, error: "", label: "Blockly XML" };
  }

  function parseBlocklyXml(Blockly, xmlText) {
    if (Blockly.Xml && typeof Blockly.Xml.textToDom === "function") {
      return Blockly.Xml.textToDom(xmlText);
    }
    const utilsXml = Blockly.utils && Blockly.utils.xml;
    if (utilsXml && typeof utilsXml.textToDom === "function") {
      return utilsXml.textToDom(xmlText);
    }
    if (typeof DOMParser !== "undefined") {
      const parser = new DOMParser();
      const doc = parser.parseFromString(xmlText, "text/xml");
      const parserError = doc.querySelector("parsererror");
      if (parserError) {
        throw new Error("Invalid Blockly XML.");
      }
      return doc.documentElement || doc;
    }
    throw new Error("Blockly XML parser is unavailable.");
  }

  function loadBlocklyXml(Blockly, xmlDom, workspace) {
    if (Blockly.Xml && typeof Blockly.Xml.domToWorkspace === "function") {
      Blockly.Xml.domToWorkspace(xmlDom, workspace);
      return;
    }
    if (Blockly.Xml && typeof Blockly.Xml.clearWorkspaceAndLoadFromXml === "function") {
      Blockly.Xml.clearWorkspaceAndLoadFromXml(xmlDom, workspace);
      return;
    }
    throw new Error("Blockly XML loader is unavailable.");
  }

  function renderBlockly(surface, payload, mediaUrl) {
    if (!surface) {
      throw new Error("Preview container is missing.");
    }
    disposeBlockly(surface);
    const Blockly = window.Blockly;
    if (!Blockly) {
      throw new Error("Blockly library is not loaded.");
    }

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
    if (mediaUrl) {
      options.media = mediaUrl;
    }

    const workspace = Blockly.inject(surface, options);
    if (payload.kind === "state") {
      const serializer = Blockly.serialization && Blockly.serialization.workspaces;
      if (!serializer || typeof serializer.load !== "function") {
        throw new Error("Blockly serialization API is unavailable.");
      }
      serializer.load(payload.value, workspace);
    } else {
      const xmlDom = parseBlocklyXml(Blockly, payload.value);
      loadBlocklyXml(Blockly, xmlDom, workspace);
    }

    if (typeof workspace.scrollCenter === "function") {
      workspace.scrollCenter();
    }
    if (typeof Blockly.svgResize === "function") {
      Blockly.svgResize(workspace);
    }
    surface._blocklyWorkspace = workspace;
  }

  function scratchLanguages() {
    const lang = String(document.documentElement.getAttribute("lang") || "")
      .trim()
      .toLowerCase();
    const primary = lang.split("-")[0] || "en";
    if (!primary || primary === "en") {
      return ["en"];
    }
    return ["en", primary];
  }

  function renderScratch(surface, text) {
    surface.innerHTML = "";
    const scratchblocks = window.scratchblocks;
    if (!scratchblocks) {
      throw new Error("Scratch renderer is not loaded.");
    }

    const pre = document.createElement("pre");
    pre.className = "scratchblocks";
    pre.id = `admin-scratch-preview-${Math.random().toString(36).slice(2, 8)}`;
    pre.textContent = text;
    surface.appendChild(pre);

    if (typeof scratchblocks.renderMatching === "function") {
      scratchblocks.renderMatching(`#${pre.id}`, {
        style: "scratch3",
        languages: scratchLanguages()
      });
      return;
    }
    if (typeof scratchblocks.render === "function") {
      scratchblocks.render(`#${pre.id}`, {
        style: "scratch3",
        languages: scratchLanguages()
      });
      return;
    }
    throw new Error("Scratch renderer API is unavailable.");
  }

  function renderCode(codeNode, codeText, codeLanguage) {
    const language = (codeLanguage || "python").trim().toLowerCase() || "python";
    codeNode.className = `language-${language}`;
    setText(codeNode, codeText);
    return language;
  }

  function pickPreviewMode(questionType, stateText, xmlText, scratchText, codeText, codeLanguage) {
    const preferredType = normalizeQuestionType(questionType);
    const stateResult = parseBlocklyStatePayload(stateText);
    const xmlResult = parseBlocklyXmlPayload(xmlText);

    let blocklyCandidate = null;
    if (stateResult.payload) {
      blocklyCandidate = {
        mode: "blockly",
        kindLabel: stateResult.label || "Blockly",
        payload: stateResult.payload,
        note: xmlResult.payload
          ? "Both blockly_state and blockly_xml are filled. Using blockly_state."
          : ""
      };
    } else if (xmlResult.payload) {
      blocklyCandidate = {
        mode: "blockly",
        kindLabel: xmlResult.label || "Blockly XML",
        payload: xmlResult.payload,
        note: stateResult.error ? `${stateResult.error} Showing blockly_xml.` : ""
      };
    } else if (stateResult.error) {
      blocklyCandidate = {
        mode: "error",
        kindLabel: "Blockly",
        message: stateResult.error,
        note: ""
      };
    }

    const scratchCandidate = scratchText
      ? {
          mode: "scratch",
          kindLabel: "Scratch",
          payload: null,
          note: ""
        }
      : null;

    const normalizedCodeLang = (codeLanguage || "python").trim().toLowerCase() || "python";
    const hasCodeText = String(codeText || "").trim().length > 0;
    const codeCandidate = hasCodeText
      ? {
          mode: "code",
          kindLabel: `Code (${normalizedCodeLang})`,
          payload: null,
          note: ""
        }
      : null;

    const candidates = {
      blockly: blocklyCandidate,
      scratch: scratchCandidate,
      code: codeCandidate
    };

    const order = preferredType
      ? [preferredType, ...["blockly", "scratch", "code"].filter((kind) => kind !== preferredType)]
      : ["blockly", "scratch", "code"];

    for (const kind of order) {
      const candidate = candidates[kind];
      if (candidate && candidate.mode !== "error") {
        return candidate;
      }
    }

    if (preferredType && candidates[preferredType] && candidates[preferredType].mode === "error") {
      return candidates[preferredType];
    }
    if (blocklyCandidate && blocklyCandidate.mode === "error" && !scratchCandidate && !codeCandidate) {
      return blocklyCandidate;
    }

    return {
      mode: "none",
      kindLabel: "Auto",
      message:
        "Enter blockly_state JSON, blockly_xml, scratchblocks_text, or code_text to preview.",
      note: ""
    };
  }

  function ensureSinglePreviewLayout(root) {
    if (!root || root.querySelector("[data-admin-preview-empty]")) {
      return;
    }
    const legacyGrid = root.querySelector(".admin-question-preview__grid");
    if (!legacyGrid) {
      return;
    }

    const section = document.createElement("section");
    section.className = "admin-question-preview__card";
    section.innerHTML = `
      <div class="admin-question-preview__heading">
        <h3 class="admin-question-preview__title">Preview</h3>
        <span class="admin-question-preview__badge" data-admin-preview-kind>Auto</span>
      </div>
      <div class="admin-question-preview__note" data-admin-preview-note hidden></div>
      <div class="admin-question-preview__empty" data-admin-preview-empty>
        Enter question data to preview.
      </div>
      <div class="admin-question-preview__surface admin-question-preview__surface--blockly" data-admin-preview-blockly></div>
      <div class="admin-question-preview__surface admin-question-preview__surface--scratch" data-admin-preview-scratch></div>
      <pre class="admin-question-preview__code" data-admin-preview-code><code data-admin-preview-code-text></code></pre>
    `;
    legacyGrid.replaceWith(section);
  }

  function initAdminQuestionPreview() {
    const root = document.querySelector("[data-admin-question-preview]");
    if (!root || root.dataset.previewBound === "1") {
      return;
    }
    root.dataset.previewBound = "1";

    const questionTypeField = document.getElementById("id_question_type");
    const blocklyStateField = document.getElementById("id_blockly_state");
    const blocklyXmlField = document.getElementById("id_blockly_xml");
    const scratchField = document.getElementById("id_scratchblocks_text");
    const codeField = document.getElementById("id_code_text");
    const codeLanguageField = document.getElementById("id_code_language");

    ensureSinglePreviewLayout(root);

    const kindBadge = root.querySelector("[data-admin-preview-kind]");
    const noteNode = root.querySelector("[data-admin-preview-note]");
    const emptyNode = root.querySelector("[data-admin-preview-empty]");
    const isSingleLayout = Boolean(emptyNode);

    const blocklySurface = pickFirst(root, [
      "[data-admin-preview-blockly]",
      "[data-admin-blockly-surface]",
      "[data-admin-blockly-stage-surface]",
      "[data-admin-blockly-xml-surface]"
    ]);
    const scratchSurface = pickFirst(root, [
      "[data-admin-preview-scratch]",
      "[data-admin-scratch-surface]"
    ]);
    const codeSurface = pickFirst(root, [
      "[data-admin-preview-code]",
      "[data-admin-code-surface]"
    ]);
    const codeTextNode = pickFirst(root, [
      "[data-admin-preview-code-text]",
      "[data-admin-code-text]"
    ]);

    const legacyBlocklyEmpty = pickFirst(root, [
      "[data-admin-blockly-empty]",
      "[data-admin-blockly-stage-empty]",
      "[data-admin-blockly-xml-empty]"
    ]);
    const legacyScratchEmpty = root.querySelector("[data-admin-scratch-empty]");
    const legacyCodeEmpty = root.querySelector("[data-admin-code-empty]");
    const mediaUrl = String(root.dataset.blocklyMediaUrl || "").trim();

    const setNote = (text) => {
      const value = String(text || "").trim();
      setText(noteNode, value);
      setVisible(noteNode, Boolean(value));
    };

    const clearSurfaces = () => {
      disposeBlockly(blocklySurface);
      if (scratchSurface) {
        scratchSurface.innerHTML = "";
      }
      setText(codeTextNode, "");
      setVisible(blocklySurface, false);
      setVisible(scratchSurface, false);
      setVisible(codeSurface, false);
      if (!isSingleLayout) {
        setText(legacyBlocklyEmpty, "Paste Blockly state/XML to preview.");
        setText(legacyScratchEmpty, "Paste scratchblocks_text to preview.");
        setText(legacyCodeEmpty, "Paste code_text to preview.");
        setVisible(legacyBlocklyEmpty, true);
        setVisible(legacyScratchEmpty, true);
        setVisible(legacyCodeEmpty, true);
      }
    };

    const showMessage = (mode, message) => {
      if (isSingleLayout) {
        setText(emptyNode, message);
        setVisible(emptyNode, true);
        return;
      }
      const target =
        mode === "scratch"
          ? legacyScratchEmpty
          : mode === "code"
            ? legacyCodeEmpty
            : legacyBlocklyEmpty;
      setText(target, message);
      setVisible(target, true);
    };

    const render = () => {
      const questionType = getValue(questionTypeField);
      const stateText = getValue(blocklyStateField);
      const xmlText = getValue(blocklyXmlField);
      const scratchText = getValue(scratchField);
      const codeText = getRawValue(codeField);
      const codeLanguage = getValue(codeLanguageField);

      const selected = pickPreviewMode(
        questionType,
        stateText,
        xmlText,
        scratchText,
        codeText,
        codeLanguage
      );

      clearSurfaces();
      setText(kindBadge, selected.kindLabel || "Auto");
      setNote(selected.note || "");

      if (selected.mode === "none") {
        if (isSingleLayout) {
          setText(emptyNode, selected.message || "Enter question data to preview.");
          setVisible(emptyNode, true);
        }
        return;
      }

      if (selected.mode === "error") {
        showMessage("blockly", selected.message || "Cannot render preview.");
        return;
      }

      try {
        if (selected.mode === "blockly") {
          renderBlockly(blocklySurface, selected.payload, mediaUrl);
          setVisible(blocklySurface, true);
          if (isSingleLayout) {
            setVisible(emptyNode, false);
          } else {
            setVisible(legacyBlocklyEmpty, false);
          }
          return;
        }
        if (selected.mode === "scratch") {
          renderScratch(scratchSurface, scratchText);
          setVisible(scratchSurface, true);
          if (isSingleLayout) {
            setVisible(emptyNode, false);
          } else {
            setVisible(legacyScratchEmpty, false);
          }
          return;
        }
        if (selected.mode === "code") {
          const language = renderCode(codeTextNode, codeText, codeLanguage);
          setText(kindBadge, `Code (${language})`);
          setVisible(codeSurface, true);
          if (isSingleLayout) {
            setVisible(emptyNode, false);
          } else {
            setVisible(legacyCodeEmpty, false);
          }
        }
      } catch (error) {
        const message = error && error.message ? error.message : String(error || "");
        showMessage(selected.mode, `Cannot render preview: ${message}`);
      }
    };

    let renderTimer = null;
    const scheduleRender = () => {
      if (renderTimer) {
        window.clearTimeout(renderTimer);
      }
      renderTimer = window.setTimeout(render, 160);
    };

    [
      questionTypeField,
      blocklyStateField,
      blocklyXmlField,
      scratchField,
      codeField,
      codeLanguageField
    ].forEach((field) => {
      if (!field) {
        return;
      }
      field.addEventListener("input", scheduleRender);
      field.addEventListener("change", scheduleRender);
    });

    window.addEventListener("resize", () => {
      const workspace = blocklySurface && blocklySurface._blocklyWorkspace;
      if (workspace && window.Blockly && typeof window.Blockly.svgResize === "function") {
        window.Blockly.svgResize(workspace);
      }
    });

    render();
  }

  document.addEventListener("DOMContentLoaded", initAdminQuestionPreview);
})();
