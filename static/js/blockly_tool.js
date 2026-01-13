function safeJsonParse(text) {
  try {
    return JSON.parse(text);
  } catch (error) {
    return null;
  }
}

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

document.addEventListener("DOMContentLoaded", () => {
  const editorEl = document.getElementById("blockly-editor");
  if (!editorEl || !window.Blockly) {
    return;
  }

  const jsonArea = document.getElementById("blockly-json");
  const xmlArea = document.getElementById("blockly-xml");

  const toolbox = {
    kind: "categoryToolbox",
    contents: [
      {
        kind: "category",
        name: "Logic",
        categorystyle: "logic_category",
        contents: [
          { kind: "block", type: "controls_if" },
          { kind: "block", type: "logic_compare" },
          { kind: "block", type: "logic_operation" },
          { kind: "block", type: "logic_negate" },
          { kind: "block", type: "logic_boolean" },
          { kind: "block", type: "logic_null" }
        ]
      },
      {
        kind: "category",
        name: "Loops",
        categorystyle: "loop_category",
        contents: [
          { kind: "block", type: "controls_repeat_ext" },
          { kind: "block", type: "controls_whileUntil" },
          { kind: "block", type: "controls_for" },
          { kind: "block", type: "controls_flow_statements" }
        ]
      },
      {
        kind: "category",
        name: "Math",
        categorystyle: "math_category",
        contents: [
          { kind: "block", type: "math_number" },
          { kind: "block", type: "math_arithmetic" },
          { kind: "block", type: "math_round" },
          { kind: "block", type: "math_random_int" }
        ]
      },
      {
        kind: "category",
        name: "Text",
        categorystyle: "text_category",
        contents: [
          { kind: "block", type: "text" },
          { kind: "block", type: "text_join" },
          { kind: "block", type: "text_length" },
          { kind: "block", type: "text_print" }
        ]
      },
      {
        kind: "category",
        name: "Lists",
        categorystyle: "list_category",
        contents: [
          { kind: "block", type: "lists_create_with" },
          { kind: "block", type: "lists_length" },
          { kind: "block", type: "lists_getIndex" }
        ]
      },
      {
        kind: "category",
        name: "Colour",
        categorystyle: "colour_category",
        contents: [{ kind: "block", type: "colour_picker" }]
      },
      {
        kind: "category",
        name: "Variables",
        categorystyle: "variable_category",
        custom: "VARIABLE"
      },
      {
        kind: "category",
        name: "Functions",
        categorystyle: "procedure_category",
        custom: "PROCEDURE"
      }
    ]
  };

  const workspace = window.Blockly.inject(editorEl, {
    toolbox,
    trashcan: true,
    scrollbars: true,
    zoom: {
      controls: true,
      wheel: true,
      startScale: 0.95,
      maxScale: 1.3,
      minScale: 0.4,
      scaleSpeed: 1.1
    }
  });

  const canSerialize =
    window.Blockly.serialization &&
    window.Blockly.serialization.workspaces &&
    typeof window.Blockly.serialization.workspaces.save === "function" &&
    typeof window.Blockly.serialization.workspaces.load === "function";

  function exportJson() {
    if (!jsonArea) {
      return;
    }
    if (!canSerialize) {
      showToast("Blockly serialization API not available.", "warning");
      return;
    }
    const state = window.Blockly.serialization.workspaces.save(workspace);
    jsonArea.value = JSON.stringify(state, null, 2);
    showToast("Exported JSON.", "success");
  }

  function exportXml() {
    if (!xmlArea) {
      return;
    }
    try {
      const dom = window.Blockly.Xml.workspaceToDom(workspace);
      const text = window.Blockly.Xml.domToPrettyText(dom);
      xmlArea.value = text;
      showToast("Exported XML.", "success");
    } catch (error) {
      showToast(`Export XML failed: ${error?.message || error}`, "error");
    }
  }

  function importJson() {
    if (!jsonArea) {
      return;
    }
    if (!canSerialize) {
      showToast("Blockly serialization API not available.", "warning");
      return;
    }
    const data = safeJsonParse(jsonArea.value);
    if (!data) {
      showToast("Invalid JSON.", "error");
      return;
    }
    workspace.clear();
    try {
      window.Blockly.serialization.workspaces.load(data, workspace);
      workspace.scrollCenter();
      window.Blockly.svgResize(workspace);
      showToast("Loaded JSON.", "success");
    } catch (error) {
      showToast(`Load JSON failed: ${error?.message || error}`, "error");
    }
  }

  function importXml() {
    if (!xmlArea) {
      return;
    }
    const text = (xmlArea.value || "").trim();
    if (!text) {
      showToast("XML is empty.", "warning");
      return;
    }
    workspace.clear();
    try {
      const dom = window.Blockly.Xml.textToDom(text);
      window.Blockly.Xml.domToWorkspace(dom, workspace);
      workspace.scrollCenter();
      window.Blockly.svgResize(workspace);
      showToast("Loaded XML.", "success");
    } catch (error) {
      showToast(`Load XML failed: ${error?.message || error}`, "error");
    }
  }

  function clearWorkspace() {
    workspace.clear();
    showToast("Cleared workspace.", "success");
  }

  function bind(selector, handler) {
    const el = document.querySelector(selector);
    if (!el) {
      return;
    }
    el.addEventListener("click", handler);
  }

  bind("[data-export-json]", exportJson);
  bind("[data-export-xml]", exportXml);
  bind("[data-import-json]", importJson);
  bind("[data-import-xml]", importXml);
  bind("[data-clear-workspace]", clearWorkspace);

  bind("[data-copy-json]", () => {
    const text = (jsonArea?.value || "").trim();
    if (!text) {
      showToast("JSON is empty.", "warning");
      return;
    }
    copyToClipboard(text)
      .then(() => showToast("Copied JSON.", "success"))
      .catch(() => showToast("Copy failed.", "error"));
  });

  bind("[data-copy-xml]", () => {
    const text = (xmlArea?.value || "").trim();
    if (!text) {
      showToast("XML is empty.", "warning");
      return;
    }
    copyToClipboard(text)
      .then(() => showToast("Copied XML.", "success"))
      .catch(() => showToast("Copy failed.", "error"));
  });

  exportJson();
  exportXml();
});

