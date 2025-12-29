const THREE_CDN = "https://cdn.jsdelivr.net/npm/three@0.160.0";

const CANVAS_DEFAULT_HEIGHT = 420;
globalThis.__legoViewerLoaded = true;

let threeDepsPromise = null;
let threeDepsBase = null;

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

async function waitForModelReady(url, status, attempts = 8) {
  for (let i = 0; i < attempts; i += 1) {
    try {
      const response = await fetch(url, { method: "HEAD", cache: "no-store" });
      if (response.status === 200) {
        return true;
      }
      if (response.status === 202) {
        setStatus(
          status,
          "Đang chuẩn bị mô hình 3D. Vui lòng đợi trong giây lát...",
          "loading"
        );
        await sleep(1200 + i * 500);
        continue;
      }
      if (response.status === 403) {
        setStatus(status, "Bạn cần mở khóa để xem mô hình 3D.", "error");
        return false;
      }
    } catch (error) {
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

  if (!canvas || !modelUrl) {
    setStatus(status, "Missing 3D model source.", "error");
    return;
  }

  try {
    root.dataset.legoBound = "true";
    setStatus(status, "Loading 3D viewer...", "loading");

    const { THREE, OrbitControls, LDrawLoader } = await loadThreeDeps(threeBase);

    if (!canvas.style.height) {
      canvas.style.height = `${CANVAS_DEFAULT_HEIGHT}px`;
    }

    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
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

    let modelGroup = null;
    let initialCamera = null;

    const loader = new LDrawLoader();
    loader.setPartsLibraryPath(partsPath);

    setStatus(status, "Loading LEGO colors...", "loading");
    await preloadLDrawMaterials(loader, partsPath);

    const ready = await waitForModelReady(modelUrl, status);
    if (!ready) {
      return;
    }
    setStatus(status, "Loading 3D model...", "loading");

    loader.load(
      modelUrl,
      (group) => {
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
        if (!event || !event.total) {
          return;
        }
        const percent = Math.min(
          100,
          Math.round((event.loaded / event.total) * 100)
        );
        setStatus(status, `Loading 3D model... ${percent}%`, "loading");
      },
      () => {
        setStatus(
          status,
          "Không tải được 3D model. Nếu file là .lxf (LEGO Digital Designer), cần chuyển đổi sang LDraw (.ldr/.mpd) bằng lxf2ldr/ldd2ldraw hoặc upload .io/.ldr/.mpd.",
          "error"
        );
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
      if (!root.isConnected) {
        resizeObserver?.disconnect?.();
        window.removeEventListener("resize", onResize);
        renderer.dispose();
        return;
      }
      requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    }

    animate();
  } catch (error) {
    console.error("LEGO viewer failed to initialize", error);
    setStatus(
      status,
      "Không tải được thư viện Three.js (module). Kiểm tra mạng/CDN (cdn.jsdelivr.net) hoặc mở Console để xem lỗi.",
      "error"
    );
  }
}

function initAll() {
  document.querySelectorAll("[data-lego-viewer]").forEach((root) => {
    initViewer(root);
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initAll, { once: true });
} else {
  initAll();
}

document.body?.addEventListener?.("htmx:afterSwap", initAll);

