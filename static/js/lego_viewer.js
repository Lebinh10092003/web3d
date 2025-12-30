const THREE_CDN = "https://cdn.jsdelivr.net/npm/three@0.160.0";

const CANVAS_DEFAULT_HEIGHT = 420;
globalThis.__legoViewerLoaded = true;

let threeDepsPromise = null;
let threeDepsBase = null;
const legoStates = new WeakMap();

function buildModuleUrls(baseUrl) {
  const base = (baseUrl || THREE_CDN).replace(/\/+$/, "");
  return {
    three: `${base}/build/three.module.js`,
    orbitControls: `${base}/examples/jsm/controls/OrbitControls.js`,
    ldrawLoader: `${base}/examples/jsm/loaders/LDrawLoader.js`,
  };
}

async function loadThreeDeps(baseUrl) {
  const base = (baseUrl || THREE_CDN).replace(/\/+$/, "");
  if (!threeDepsPromise || threeDepsBase !== base) {
    threeDepsBase = base;
    threeDepsPromise = (async () => {
      const modules = buildModuleUrls(base);
      const [THREE, orbitModule, ldrawModule] = await Promise.all([
        import(modules.three),
        import(modules.orbitControls),
        import(modules.ldrawLoader),
      ]);
      return {
        THREE,
        OrbitControls: orbitModule.OrbitControls,
        LDrawLoader: ldrawModule.LDrawLoader,
      };
    })();
  }
  return threeDepsPromise;
}
function ensureTrailingSlash(value) {
  if (!value) {
    return "/";
  }
  return value.endsWith("/") ? value : `${value}/`;
}

function sleep(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

async function waitForModelReady(url, status, messages, signal, attempts = 8) {
  for (let i = 0; i < attempts; i += 1) {
    if (signal && signal.aborted) {
      return false;
    }
    try {
      const response = await fetch(url, {
        method: "HEAD",
        cache: "no-store",
        signal
      });
      if (response.status === 200) {
        return true;
      }
      if (response.status === 202) {
        setStatus(status, messages.preparingModel, "loading");
        await sleep(1200 + i * 500);
        continue;
      }
      if (response.status === 403) {
        setStatus(status, messages.unlockRequired, "error");
        return false;
      }
      if (response.status !== 200) {
        setStatus(status, messages.loadFailed, "error");
        return false;
      }
    } catch (error) {
      if (error && error.name === "AbortError") {
        return false;
      }
      await sleep(1200);
    }
    break;
  }
  return true;
}


function setStatus(node, message, level = "") {
  if (!node) {
    return;
  }
  const textNode = node.querySelector("[data-lego-status-text]") || node;
  textNode.textContent = message;
  node.dataset.level = level;
  node.dataset.visible = message ? "true" : "false";
}

function getMessage(root, key, fallback) {
  if (!root || !root.dataset) {
    return fallback;
  }
  return root.dataset[key] || fallback;
}

function cancelViewer(root, reason) {
  if (!root) {
    return;
  }
  root.dataset.legoCancel = "true";
  root.dataset.legoBound = "";
  root.dataset.legoStarted = "";
  root.dataset.legoAutoload = "false";
  const startWrap = root.querySelector("[data-lego-start-wrap]");
  if (startWrap) {
    startWrap.hidden = false;
  }
  const state = legoStates.get(root);
  const statusNode = state?.statusNode || root.querySelector("[data-lego-status]");
  if (state && !state.canceled) {
    state.canceled = true;
    if (state.abortController) {
      try {
        state.abortController.abort();
      } catch {}
    }
    if (state.cleanup) {
      state.cleanup();
    }
  }
  if (statusNode) {
    setStatus(
      statusNode,
      reason || root.dataset.msgCanceled || "Canceled 3D loading.",
      "error"
    );
  }
}

function cancelAllViewers(reason) {
  document.querySelectorAll("[data-lego-viewer]").forEach((root) => {
    cancelViewer(root, reason);
  });
}

async function preloadLDrawMaterials(loader, partsPath) {
  if (!loader || typeof loader.preloadMaterials !== "function") {
    return;
  }

  const configUrl = `${ensureTrailingSlash(partsPath)}LDConfig.ldr`;

  async function attempt(preloadFn, timeoutMs = 4000) {
    return new Promise((resolve, reject) => {
      let settled = false;
      const timeoutId = window.setTimeout(() => {
        finish(false, new Error("Timed out while loading LDraw colors."));
      }, timeoutMs);
      const finish = (result, error) => {
        if (settled) {
          return;
        }
        settled = true;
        window.clearTimeout(timeoutId);
        if (result) {
          resolve();
        } else {
          reject(error || new Error("Failed to preload LDraw materials."));
        }
      };

      try {
        const ret = preloadFn(
          () => finish(true),
          (error) => finish(false, error)
        );
        if (ret && typeof ret.then === "function") {
          ret.then(() => finish(true)).catch((error) => finish(false, error));
        }
      } catch (error) {
        finish(false, error);
      }
    });
  }

  try {
    await attempt((onLoad, onError) =>
      loader.preloadMaterials(configUrl, onLoad, undefined, onError)
    );
    return;
  } catch {}

  try {
    const ret = loader.preloadMaterials();
    if (ret && typeof ret.then === "function") {
      await ret;
    }
    return;
  } catch {}

  try {
    await attempt((onLoad, onError) =>
      loader.preloadMaterials(onLoad, undefined, onError)
    );
  } catch {}
}

function fitCamera(THREE, camera, controls, object, offset = 1.25) {
  const box = new THREE.Box3().setFromObject(object);
  if (box.isEmpty()) {
    return null;
  }
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const maxDim = Math.max(size.x, size.y, size.z);
  const fitHeightDistance = maxDim / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)));
  const fitWidthDistance = fitHeightDistance / camera.aspect;
  const distance = offset * Math.max(fitHeightDistance, fitWidthDistance);

  const direction = controls.target
    .clone()
    .sub(camera.position)
    .normalize()
    .multiplyScalar(distance);

  camera.near = Math.max(0.1, distance / 200);
  camera.far = Math.max(1000, distance * 20);
  camera.updateProjectionMatrix();

  controls.target.copy(center);
  camera.position.copy(controls.target).sub(direction);
  controls.update();
  return { center, distance };
}

function setRendererSize(renderer, canvas, camera) {
  const width = canvas.clientWidth || canvas.parentElement?.clientWidth || 1;
  const height = canvas.clientHeight || CANVAS_DEFAULT_HEIGHT;
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
}

function buildScene(THREE) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xffffff);

  const ambient = new THREE.AmbientLight(0xffffff, 0.75);
  scene.add(ambient);

  const directional = new THREE.DirectionalLight(0xffffff, 0.9);
  directional.position.set(200, 400, 300);
  scene.add(directional);

  const grid = new THREE.GridHelper(400, 40, 0x9aa0a6, 0xdadce0);
  grid.material.transparent = true;
  grid.material.opacity = 0.3;
  scene.add(grid);

  return scene;
}

async function initViewer(root) {
  if (!root || root.dataset.legoBound === "true") {
    return;
  }

  const canvas = root.querySelector("[data-lego-canvas]");
  const status = root.querySelector("[data-lego-status]");
  const flipButton = root.querySelector("[data-lego-flip]");
  const fitButton = root.querySelector("[data-lego-fit]");
  const resetButton = root.querySelector("[data-lego-reset]");

  const modelUrl = root.dataset.modelUrl;
  const partsPath = ensureTrailingSlash(root.dataset.partsPath);
  const zoomEnabled = root.dataset.zoomEnabled !== "false";
  const threeBase = root.dataset.threeBase;
  const fitOffset = zoomEnabled ? 1.25 : 2.85;
  const messages = {
    loadingViewer: getMessage(root, "msgLoadingViewer", "Loading 3D viewer..."),
    loadingColors: getMessage(root, "msgLoadingColors", "Loading LEGO colors..."),
    loadingModel: getMessage(root, "msgLoadingModel", "Loading 3D model..."),
    loadingModelProgress: getMessage(
      root,
      "msgLoadingModelProgress",
      "Loading 3D model... {percent}%"
    ),
    missingModel: getMessage(root, "msgMissingModel", "Missing 3D model source."),
    preparingModel: getMessage(
      root,
      "msgPreparingModel",
      "Preparing 3D model. Please wait a moment..."
    ),
    unlockRequired: getMessage(
      root,
      "msgUnlockRequired",
      "Unlock required to view this 3D model."
    ),
    loadFailed: getMessage(root, "msgLoadFailed", "Could not load 3D model."),
    threeFailed: getMessage(
      root,
      "msgThreeFailed",
      "Could not load Three.js (module)."
    )
  };
  const autoload = root.dataset.legoAutoload === "true";
  const started = root.dataset.legoStarted === "true";
  if (!autoload && !started) {
    return;
  }

  if (!canvas || !modelUrl) {
    setStatus(status, messages.missingModel, "error");
    return;
  }
  if (root.dataset.legoCancel === "true") {
    setStatus(status, root.dataset.msgCanceled || "Canceled 3D loading.", "error");
    return;
  }

  const abortController = new AbortController();
  const state = {
    canceled: false,
    abortController,
    cleanup: null,
    statusNode: status,
    cleaned: false
  };
  legoStates.set(root, state);

  try {
    root.dataset.legoBound = "true";
    setStatus(status, messages.loadingViewer, "loading");

    const { THREE, OrbitControls, LDrawLoader } = await loadThreeDeps(threeBase);
    if (state.canceled) {
      return;
    }

    if (!canvas.style.height) {
      canvas.style.height = `${CANVAS_DEFAULT_HEIGHT}px`;
    }

    let renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;

    const scene = buildScene(THREE);
    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
    camera.position.set(320, 260, 320);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.rotateSpeed = 0.7;
    controls.enableZoom = zoomEnabled;

    setRendererSize(renderer, canvas, camera);

    const onResize = () => setRendererSize(renderer, canvas, camera);
    let resizeObserver = null;
    if (typeof ResizeObserver !== "undefined") {
      resizeObserver = new ResizeObserver(onResize);
      resizeObserver.observe(root);
    } else {
      window.addEventListener("resize", onResize);
    }

    const cleanup = () => {
      if (state.cleaned) {
        return;
      }
      state.cleaned = true;
      resizeObserver?.disconnect?.();
      window.removeEventListener("resize", onResize);
      if (renderer) {
        renderer.dispose();
        renderer = null;
      }
    };
    state.cleanup = cleanup;

    let modelGroup = null;
    let initialCamera = null;

    const loader = new LDrawLoader();
    loader.setPartsLibraryPath(partsPath);

    setStatus(status, messages.loadingColors, "loading");
    await preloadLDrawMaterials(loader, partsPath);
    if (state.canceled) {
      cleanup();
      return;
    }

    const ready = await waitForModelReady(
      modelUrl,
      status,
      messages,
      abortController.signal
    );
    if (!ready) {
      cleanup();
      return;
    }
    if (state.canceled) {
      cleanup();
      return;
    }
    setStatus(status, messages.loadingModel, "loading");

    loader.load(
      modelUrl,
      (group) => {
        if (state.canceled) {
          cleanup();
          return;
        }
        modelGroup = group;

        const baseTransform = {
          position: group.position.clone(),
          rotation: group.rotation.clone(),
        };
        let flipped = true;

        const applyTransform = () => {
          group.position.copy(baseTransform.position);
          group.rotation.copy(baseTransform.rotation);
          if (flipped) {
            group.rotation.x += Math.PI;
          }
          group.updateMatrixWorld(true);
          const box = new THREE.Box3().setFromObject(group);
          if (!box.isEmpty()) {
            group.position.y -= box.min.y;
            group.updateMatrixWorld(true);
          }
        };

        applyTransform();
        scene.add(group);
        fitCamera(THREE, camera, controls, group, fitOffset);
        initialCamera = {
          position: camera.position.clone(),
          target: controls.target.clone(),
        };
        setStatus(status, "", "");

        if (flipButton) {
          flipButton.addEventListener("click", () => {
            if (!modelGroup) {
              return;
            }
            flipped = !flipped;
            applyTransform();
            fitCamera(THREE, camera, controls, modelGroup, fitOffset);
            initialCamera = {
              position: camera.position.clone(),
              target: controls.target.clone(),
            };
          });
        }
      },
      (event) => {
        if (state.canceled) {
          return;
        }
        if (!event || !event.total) {
          return;
        }
        const percent = Math.min(
          100,
          Math.round((event.loaded / event.total) * 100)
        );
        const template = messages.loadingModelProgress;
        setStatus(status, template.replace("{percent}", String(percent)), "loading");
      },
      () => {
        if (state.canceled) {
          cleanup();
          return;
        }
        setStatus(status, messages.loadFailed, "error");
      }
    );

    if (fitButton) {
      fitButton.addEventListener("click", () => {
        if (!modelGroup) {
          return;
        }
        fitCamera(THREE, camera, controls, modelGroup, fitOffset);
      });
    }

    if (resetButton) {
      resetButton.addEventListener("click", () => {
        if (!initialCamera) {
          return;
        }
        camera.position.copy(initialCamera.position);
        controls.target.copy(initialCamera.target);
        controls.update();
      });
    }

    function animate() {
      if (state.canceled || !root.isConnected) {
        cleanup();
        return;
      }
      requestAnimationFrame(animate);
      if (document.hidden) {
        return;
      }
      controls.update();
      renderer.render(scene, camera);
    }

    animate();
  } catch (error) {
    console.error("LEGO viewer failed to initialize", error);
    setStatus(
      status,
      messages.threeFailed,
      "error"
    );
  }
}

function startViewer(root) {
  if (!root) {
    return;
  }
  root.dataset.legoAutoload = "true";
  root.dataset.legoStarted = "true";
  root.dataset.legoCancel = "";
  const startWrap = root.querySelector("[data-lego-start-wrap]");
  if (startWrap) {
    startWrap.hidden = true;
  }
  initViewer(root);
}

function bindStartButtons() {
  document.querySelectorAll("[data-lego-viewer]").forEach((root) => {
    const startWrap = root.querySelector("[data-lego-start-wrap]");
    if (startWrap) {
      const autoload = root.dataset.legoAutoload === "true";
      const started = root.dataset.legoStarted === "true";
      startWrap.hidden = autoload || started;
    }
    const startButton = root.querySelector("[data-lego-start]");
    if (!startButton || startButton.dataset.bound === "true") {
      return;
    }
    startButton.dataset.bound = "true";
    startButton.addEventListener("click", () => startViewer(root));
  });
}

function initAll() {
  bindStartButtons();
  document.querySelectorAll("[data-lego-viewer]").forEach((root) => {
    if (
      root.dataset.legoAutoload === "true" ||
      root.dataset.legoStarted === "true"
    ) {
      initViewer(root);
    }
  });
}

globalThis.startLegoViewer = startViewer;

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initAll, { once: true });
} else {
  initAll();
}

document.body?.addEventListener?.("htmx:afterSwap", initAll);

document.addEventListener("click", (event) => {
  const target = event.target;
  if (!target) {
    return;
  }
  if (target.closest("[data-lego-viewer]")) {
    return;
  }
  if (target.closest("[data-owner-modal-open]")) {
    return;
  }
  if (target.closest("[data-back-button]")) {
    cancelAllViewers();
    return;
  }
  const link = target.closest("a[href]");
  if (!link) {
    return;
  }
  const href = link.getAttribute("href") || "";
  if (href.startsWith("#") || href.startsWith("javascript:")) {
    return;
  }
  cancelAllViewers();
});

document.body?.addEventListener?.("htmx:beforeRequest", () => {
  cancelAllViewers();
});

window.addEventListener("pagehide", () => cancelAllViewers());
window.addEventListener("beforeunload", () => cancelAllViewers());

