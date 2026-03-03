(function () {
  function getValue(field) {
    if (!field || typeof field.value !== "string") {
      return "";
    }
    return field.value.replace(/\r\n/g, "\n").trim();
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

  function parseBlocklyPayload(stateText, xmlText) {
    if (stateText) {
      try {
        const parsed = JSON.parse(stateText);
        if (parsed && typeof parsed === "object") {
          return { payload: { kind: "state", value: parsed }, error: "" };
        }
        if (typeof parsed === "string" && parsed.trim()) {
          return { payload: { kind: "xml", value: parsed.trim() }, error: "" };
        }
        return { payload: null, error: "blockly_state does not contain valid Blockly data." };
      } catch (error) {
        if (xmlText) {
          return { payload: { kind: "xml", value: xmlText }, error: "" };
        }
        return { payload: null, error: "blockly_state JSON is invalid." };
      }
    }
    if (xmlText) {
      return { payload: { kind: "xml", value: xmlText }, error: "" };
    }
    return { payload: null, error: "" };
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

  function renderBlockly(surface, emptyNode, payload, mediaUrl) {
    disposeBlockly(surface);
    if (!payload) {
      setVisible(surface, false);
      return;
    }

    const Blockly = window.Blockly;
    if (!Blockly) {
      setText(emptyNode, "Blockly library is not loaded.");
      setVisible(emptyNode, true);
      setVisible(surface, false);
      return;
    }

    try {
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
      setVisible(emptyNode, false);
      setVisible(surface, true);
    } catch (error) {
      disposeBlockly(surface);
      const message = error && error.message ? error.message : String(error || "");
      setText(emptyNode, `Cannot render Blockly preview: ${message}`);
      setVisible(emptyNode, true);
      setVisible(surface, false);
    }
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

  function renderScratch(surface, emptyNode, text) {
    surface.innerHTML = "";
    if (!text) {
      setVisible(surface, false);
      return;
    }

    const scratchblocks = window.scratchblocks;
    if (!scratchblocks) {
      setText(emptyNode, "Scratch renderer is not loaded.");
      setVisible(emptyNode, true);
      setVisible(surface, false);
      return;
    }

    const pre = document.createElement("pre");
    pre.className = "scratchblocks";
    pre.id = `admin-scratch-preview-${Math.random().toString(36).slice(2, 8)}`;
    pre.textContent = text;
    surface.appendChild(pre);

    try {
      if (typeof scratchblocks.renderMatching === "function") {
        scratchblocks.renderMatching(`#${pre.id}`, {
          style: "scratch3",
          languages: scratchLanguages()
        });
      } else if (typeof scratchblocks.render === "function") {
        scratchblocks.render(`#${pre.id}`, {
          style: "scratch3",
          languages: scratchLanguages()
        });
      } else {
        throw new Error("Scratch renderer API is unavailable.");
      }
      setVisible(emptyNode, false);
      setVisible(surface, true);
    } catch (error) {
      const message = error && error.message ? error.message : String(error || "");
      setText(emptyNode, `Cannot render Scratch preview: ${message}`);
      setVisible(emptyNode, true);
      setVisible(surface, false);
    }
  }

  function renderCode(surface, codeNode, emptyNode, languageBadge, codeText, codeLanguage) {
    const language = (codeLanguage || "python").trim().toLowerCase() || "python";
    setText(languageBadge, language);
    if (!codeText) {
      setVisible(surface, false);
      setVisible(emptyNode, true);
      return;
    }
    codeNode.className = `language-${language}`;
    setText(codeNode, codeText);
    setVisible(emptyNode, false);
    setVisible(surface, true);
  }

  function initAdminQuestionPreview() {
    const root = document.querySelector("[data-admin-question-preview]");
    if (!root || root.dataset.previewBound === "1") {
      return;
    }
    root.dataset.previewBound = "1";

    const blocklyStateField = document.getElementById("id_blockly_state");
    const blocklyXmlField = document.getElementById("id_blockly_xml");
    const scratchField = document.getElementById("id_scratchblocks_text");
    const codeField = document.getElementById("id_code_text");
    const codeLanguageField = document.getElementById("id_code_language");

    const blocklySurface = root.querySelector("[data-admin-blockly-surface]");
    const blocklyEmpty = root.querySelector("[data-admin-blockly-empty]");
    const scratchSurface = root.querySelector("[data-admin-scratch-surface]");
    const scratchEmpty = root.querySelector("[data-admin-scratch-empty]");
    const codeSurface = root.querySelector("[data-admin-code-surface]");
    const codeEmpty = root.querySelector("[data-admin-code-empty]");
    const codeTextNode = root.querySelector("[data-admin-code-text]");
    const codeLanguageBadge = root.querySelector("[data-admin-code-language]");
    const mediaUrl = String(root.dataset.blocklyMediaUrl || "").trim();

    const render = () => {
      const stateText = getValue(blocklyStateField);
      const xmlText = getValue(blocklyXmlField);
      const scratchText = getValue(scratchField);
      const codeText = codeField && typeof codeField.value === "string"
        ? codeField.value.replace(/\r\n/g, "\n")
        : "";
      const codeLanguage = getValue(codeLanguageField);

      const blocklyResult = parseBlocklyPayload(stateText, xmlText);
      if (!blocklyResult.payload) {
        disposeBlockly(blocklySurface);
        if (blocklyResult.error) {
          setText(blocklyEmpty, blocklyResult.error);
        } else {
          setText(blocklyEmpty, "Paste Blockly state/XML to preview.");
        }
        setVisible(blocklyEmpty, true);
        setVisible(blocklySurface, false);
      } else {
        renderBlockly(blocklySurface, blocklyEmpty, blocklyResult.payload, mediaUrl);
      }

      if (!scratchText) {
        scratchSurface.innerHTML = "";
        setText(scratchEmpty, "Paste scratchblocks_text to preview.");
        setVisible(scratchEmpty, true);
        setVisible(scratchSurface, false);
      } else {
        renderScratch(scratchSurface, scratchEmpty, scratchText);
      }

      renderCode(
        codeSurface,
        codeTextNode,
        codeEmpty,
        codeLanguageBadge,
        codeText,
        codeLanguage
      );
    };

    let renderTimer = null;
    const scheduleRender = () => {
      if (renderTimer) {
        window.clearTimeout(renderTimer);
      }
      renderTimer = window.setTimeout(render, 180);
    };

    [blocklyStateField, blocklyXmlField, scratchField, codeField, codeLanguageField].forEach(
      (field) => {
        if (!field) {
          return;
        }
        field.addEventListener("input", scheduleRender);
        field.addEventListener("change", scheduleRender);
      }
    );

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
