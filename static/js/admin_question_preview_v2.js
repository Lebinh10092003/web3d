(function () {
  window.__adminQuestionPreviewVersion = "2026-03-03-visible-v3";

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

  function patchBlocklyVariableApis(Blockly) {
    const workspaceProto = Blockly && Blockly.Workspace ? Blockly.Workspace.prototype : null;
    if (!workspaceProto || typeof workspaceProto.getVariableMap !== "function") {
      return;
    }
    const patch = (name, resolver) => {
      const current = workspaceProto[name];
      if (current && current.__adminPreviewPatched) {
        return;
      }
      workspaceProto[name] = function (...args) {
        return resolver.call(this, ...args);
      };
      workspaceProto[name].__adminPreviewPatched = true;
      workspaceProto[name].__adminPreviewOriginal = current;
    };
    patch("getAllVariables", function () {
      const map = this.getVariableMap ? this.getVariableMap() : null;
      return map && typeof map.getAllVariables === "function" ? map.getAllVariables() : [];
    });
    patch("getVariableById", function (id) {
      const map = this.getVariableMap ? this.getVariableMap() : null;
      return map && typeof map.getVariableById === "function" ? map.getVariableById(id) : null;
    });
    patch("getVariable", function (name, type) {
      const map = this.getVariableMap ? this.getVariableMap() : null;
      return map && typeof map.getVariable === "function" ? map.getVariable(name, type) : null;
    });
  }

  function ensureBlocklyColourBlocks(Blockly) {
    if (!Blockly || !Blockly.Blocks || Blockly.__adminPreviewColourBlocksEnsured) {
      return;
    }
    const requiredTypes = ["colour_picker", "colour_random", "colour_rgb", "colour_blend"];
    const missingTypes = requiredTypes.filter((type) => !Blockly.Blocks[type]);
    if (!missingTypes.length || typeof Blockly.defineBlocksWithJsonArray !== "function") {
      Blockly.__adminPreviewColourBlocksEnsured = true;
      return;
    }
    const definitions = [];
    if (missingTypes.includes("colour_picker")) {
      definitions.push({
        type: "colour_picker",
        message0: "%1",
        args0: [{ type: "field_colour", name: "COLOUR", colour: "#ff0000" }],
        output: "Colour",
        style: "colour_blocks"
      });
    }
    if (missingTypes.includes("colour_random")) {
      definitions.push({
        type: "colour_random",
        message0: "%{BKY_COLOUR_RANDOM_TITLE}",
        output: "Colour",
        style: "colour_blocks"
      });
    }
    if (missingTypes.includes("colour_rgb")) {
      definitions.push({
        type: "colour_rgb",
        message0: "%{BKY_COLOUR_RGB_TITLE}",
        message1: "%{BKY_COLOUR_RGB_RED} %1",
        args1: [{ type: "input_value", name: "RED", check: "Number" }],
        message2: "%{BKY_COLOUR_RGB_GREEN} %1",
        args2: [{ type: "input_value", name: "GREEN", check: "Number" }],
        message3: "%{BKY_COLOUR_RGB_BLUE} %1",
        args3: [{ type: "input_value", name: "BLUE", check: "Number" }],
        inputsInline: true,
        output: "Colour",
        style: "colour_blocks"
      });
    }
    if (missingTypes.includes("colour_blend")) {
      definitions.push({
        type: "colour_blend",
        message0: "%{BKY_COLOUR_BLEND_TITLE}",
        message1: "%{BKY_COLOUR_BLEND_COLOUR1} %1",
        args1: [{ type: "input_value", name: "COLOUR1", check: "Colour" }],
        message2: "%{BKY_COLOUR_BLEND_COLOUR2} %1",
        args2: [{ type: "input_value", name: "COLOUR2", check: "Colour" }],
        message3: "%{BKY_COLOUR_BLEND_RATIO} %1",
        args3: [{ type: "input_value", name: "RATIO", check: "Number" }],
        inputsInline: true,
        output: "Colour",
        style: "colour_blocks"
      });
    }
    try {
      Blockly.defineBlocksWithJsonArray(definitions);
      Blockly.__adminPreviewColourBlocksEnsured = true;
    } catch (error) {
      // keep default behavior if this optional compatibility step fails
    }
  }

  function expectedBlocklyRootBlockCount(payload) {
    if (!payload) {
      return 0;
    }
    if (payload.kind === "state") {
      const root = payload.value && payload.value.blocks && payload.value.blocks.blocks;
      return Array.isArray(root) ? root.length : 0;
    }
    if (payload.kind === "xml") {
      return /<block\b/i.test(String(payload.value || "")) ? 1 : 0;
    }
    return 0;
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

  function ensureBlocklySurfaceReady(surface) {
    if (!surface) {
      return;
    }
    if (surface.hidden) {
      surface.hidden = false;
    }
    surface.style.display = "block";
    if (!surface.style.minHeight) {
      surface.style.minHeight = "260px";
    }
    if (surface.clientHeight <= 2) {
      surface.style.height = "260px";
    }
    // Force layout so Blockly reads final dimensions instead of stale hidden metrics.
    surface.getBoundingClientRect();
  }

  function enforceBlocklyInnerHeight(surface) {
    if (!surface) {
      return;
    }
    const targetHeight = Math.max(surface.clientHeight || 0, 260);
    const injectionDiv = surface.querySelector(".injectionDiv");
    if (injectionDiv) {
      injectionDiv.style.height = `${targetHeight}px`;
      injectionDiv.style.minHeight = `${targetHeight}px`;
    }
    const svg = surface.querySelector("svg.blocklySvg");
    if (svg) {
      svg.style.height = `${targetHeight}px`;
      svg.style.minHeight = `${targetHeight}px`;
      svg.setAttribute("height", String(targetHeight));
    }
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
    ensureBlocklySurfaceReady(surface);
    const Blockly = window.Blockly;
    if (!Blockly) {
      throw new Error("Blockly library is not loaded.");
    }
    patchBlocklyVariableApis(Blockly);
    ensureBlocklyColourBlocks(Blockly);
    try {
      if (!Blockly.__adminPreviewLocaleApplied && typeof Blockly.setLocale === "function" && Blockly.Msg) {
        Blockly.setLocale(Blockly.Msg);
        Blockly.__adminPreviewLocaleApplied = true;
      }
    } catch (error) {
      // ignore locale issues
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
    enforceBlocklyInnerHeight(surface);
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
    enforceBlocklyInnerHeight(surface);
    const metrics =
      typeof workspace.getMetrics === "function" ? workspace.getMetrics() : null;
    const viewWidth = metrics && typeof metrics.viewWidth === "number" ? metrics.viewWidth : null;
    const viewHeight =
      metrics && typeof metrics.viewHeight === "number" ? metrics.viewHeight : null;
    const surfaceRect =
      surface && typeof surface.getBoundingClientRect === "function"
        ? surface.getBoundingClientRect()
        : null;
    const blockCount =
      typeof workspace.getAllBlocks === "function" ? workspace.getAllBlocks(false).length : null;
    const expectedRootBlocks = expectedBlocklyRootBlockCount(payload);
    if (
      expectedRootBlocks > 0 &&
      typeof workspace.getAllBlocks === "function" &&
      blockCount === 0
    ) {
      throw new Error(
        "No blocks were rendered. Check custom block definitions used by this question."
      );
    }
    const needsResizeRetry =
      blockCount > 0 &&
      ((typeof viewWidth === "number" && viewWidth <= 2) ||
        (typeof viewHeight === "number" && viewHeight <= 2) ||
        (surfaceRect && (surfaceRect.width <= 2 || surfaceRect.height <= 2)));
    if (needsResizeRetry) {
      window.setTimeout(() => resizeBlocklyWorkspace(surface), 200);
      window.setTimeout(() => resizeBlocklyWorkspace(surface), 450);
    }
    surface._blocklyWorkspace = workspace;
    return {
      blockCount,
      viewWidth,
      viewHeight,
      needsResizeRetry,
      surfaceWidth: surfaceRect && typeof surfaceRect.width === "number" ? surfaceRect.width : null,
      surfaceHeight:
        surfaceRect && typeof surfaceRect.height === "number" ? surfaceRect.height : null
    };
  }

  function resizeBlocklyWorkspace(surface) {
    ensureBlocklySurfaceReady(surface);
    const workspace = surface && surface._blocklyWorkspace;
    if (!workspace || !window.Blockly || typeof window.Blockly.svgResize !== "function") {
      return;
    }
    enforceBlocklyInnerHeight(surface);
    window.Blockly.svgResize(workspace);
    if (typeof workspace.scrollCenter === "function") {
      workspace.scrollCenter();
    }
    if (typeof workspace.getMetrics === "function") {
      const metrics = workspace.getMetrics();
      if (metrics && typeof metrics.viewHeight === "number" && metrics.viewHeight <= 2) {
        surface.style.height = "320px";
        enforceBlocklyInnerHeight(surface);
        window.Blockly.svgResize(workspace);
      }
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
        <div class="admin-question-preview__actions">
          <span class="admin-question-preview__badge" data-admin-preview-kind>Auto</span>
          <button type="button" class="button admin-question-preview__refresh" data-admin-preview-refresh>
            Load preview
          </button>
        </div>
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
    const refreshButton = root.querySelector("[data-admin-preview-refresh]");
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
          setVisible(blocklySurface, true);
          const blocklyResult = renderBlockly(blocklySurface, selected.payload, mediaUrl);
          window.requestAnimationFrame(() => resizeBlocklyWorkspace(blocklySurface));
          window.setTimeout(() => resizeBlocklyWorkspace(blocklySurface), 120);
          const diagnostics = [];
          if (blocklyResult && typeof blocklyResult.blockCount === "number") {
            diagnostics.push(`Rendered ${blocklyResult.blockCount} block(s).`);
          }
          if (
            blocklyResult &&
            typeof blocklyResult.viewWidth === "number" &&
            typeof blocklyResult.viewHeight === "number"
          ) {
            diagnostics.push(
              `Viewport ${Math.round(blocklyResult.viewWidth)}x${Math.round(blocklyResult.viewHeight)}.`
            );
          }
          if (
            blocklyResult &&
            typeof blocklyResult.surfaceWidth === "number" &&
            typeof blocklyResult.surfaceHeight === "number"
          ) {
            diagnostics.push(
              `Surface ${Math.round(blocklyResult.surfaceWidth)}x${Math.round(blocklyResult.surfaceHeight)}.`
            );
          }
          if (blocklyResult && blocklyResult.needsResizeRetry) {
            diagnostics.push("Workspace viewport was small; auto-resize retry applied.");
          }
          const noteText = [selected.note || "", diagnostics.join(" ")].filter(Boolean).join(" ");
          setNote(noteText);
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
        if (selected.mode === "blockly") {
          disposeBlockly(blocklySurface);
          setVisible(blocklySurface, false);
          if (codeSurface && codeTextNode && selected.payload) {
            const fallbackText =
              selected.payload.kind === "state"
                ? JSON.stringify(selected.payload.value || {}, null, 2)
                : String(selected.payload.value || "");
            codeTextNode.className = "language-json";
            setText(codeTextNode, fallbackText);
            setVisible(codeSurface, true);
          }
        }
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

    if (refreshButton) {
      refreshButton.addEventListener("click", (event) => {
        event.preventDefault();
        render();
      });
    }

    window.addEventListener("resize", () => {
      const workspace = blocklySurface && blocklySurface._blocklyWorkspace;
      if (workspace && window.Blockly && typeof window.Blockly.svgResize === "function") {
        window.Blockly.svgResize(workspace);
      }
    });

    render();
  }

  window.AdminQuestionPreview = window.AdminQuestionPreview || {};
  window.AdminQuestionPreview.init = initAdminQuestionPreview;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAdminQuestionPreview);
  } else {
    initAdminQuestionPreview();
  }
})();
